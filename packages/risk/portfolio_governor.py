"""Phase 6: Portfolio Risk Governor.

Distinct from `packages/risk/governor.py: DeterministicRiskGovernor`, which sizes and
approves a SINGLE trade intent against NAV-level rules (0.25% risk/trade, symbol/total
exposure caps — the existing production per-trade governor used by both paper trading and
backtesting). This module operates one level up: given a candidate that has already cleared
the per-trade governor, decide whether the PORTFOLIO as a whole can additionally take it on,
considering every other open/proposed position, correlation, and portfolio-level loss/
drawdown limits. Neither governor replaces the other; a candidate must clear both.

Every decision is exactly one of APPROVE / REDUCE / REJECT / HALT, with the requested vs.
approved risk and full reasoning attached. Missing portfolio state is never treated as "no
risk" — it is treated as the worst case (HALT) until real state is available. Nothing here
is ever overridden by an LLM/market-context output (Section 11: "The LLM layer must never
override this service" — this module doesn't import from packages.intelligence.market_context
or packages.llm at all, structurally, not just by convention).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, FrozenSet, List, Optional

from packages.candidates.models import TradeCandidate
from packages.domain.entities import CorrelationSnapshot, PortfolioRiskDecision
from packages.domain.enums import PortfolioRiskDecisionType
from packages.ports.interfaces import PortfolioSnapshot

POLICY_VERSION = "portfolio_risk_v1"


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    version: str = POLICY_VERSION
    max_risk_per_candidate_pct: Decimal = Decimal("0.25")
    max_total_open_risk_pct: Decimal = Decimal("2.0")
    max_simultaneous_positions: int = 5
    max_single_asset_exposure_pct: Decimal = Decimal("20.0")
    max_same_direction_exposure_pct: Decimal = Decimal("50.0")
    max_correlated_exposure_pct: Decimal = Decimal("30.0")
    correlated_threshold: Decimal = Decimal("0.7")  # |correlation| >= this counts as "correlated"
    daily_loss_limit_pct: Decimal = Decimal("1.5")
    weekly_loss_limit_pct: Decimal = Decimal("4.0")
    portfolio_drawdown_limit_pct: Decimal = Decimal("8.0")


@dataclass(frozen=True)
class RiskEvaluationContext:
    """Everything the governor needs beyond the candidate/requested-risk/portfolio triple —
    kept explicit rather than pulled from a global so a HALT/REJECT decision is always
    reproducible from its recorded inputs."""

    evidence_actionable: bool
    is_stale_data: bool = False
    is_low_liquidity: bool = False
    correlation_snapshots: List[CorrelationSnapshot] = field(default_factory=list)


class BaselinePortfolioRiskGovernor:
    def __init__(self, policy: Optional[PortfolioRiskPolicy] = None) -> None:
        self.policy = policy if policy is not None else PortfolioRiskPolicy()

    def evaluate(
        self,
        candidate: TradeCandidate,
        requested_risk_pct: Decimal,
        portfolio: PortfolioSnapshot,
        context: RiskEvaluationContext,
    ) -> PortfolioRiskDecision:
        p = self.policy

        def decide(
            decision_type: PortfolioRiskDecisionType, approved_risk: Decimal, reasons: List[str],
        ) -> PortfolioRiskDecision:
            return PortfolioRiskDecision(
                policy_version=p.version,
                candidate_id=candidate.candidate_id,
                decision=decision_type,
                requested_risk_pct=requested_risk_pct,
                approved_risk_pct=approved_risk,
                reason_codes=reasons,
            )

        # 1. Missing portfolio state -> conservative HALT, never an implicit APPROVE.
        if not portfolio.available:
            return decide(PortfolioRiskDecisionType.HALT, Decimal("0"), ["PORTFOLIO_STATE_UNAVAILABLE"])

        # 2. Kill switch is absolute.
        if portfolio.kill_switch_active:
            return decide(PortfolioRiskDecisionType.HALT, Decimal("0"), ["KILL_SWITCH_ACTIVE"])

        # 3. Portfolio drawdown circuit breaker — also absolute (halts new risk-taking, not
        # just this one candidate).
        drawdown_breached = (
            portfolio.current_drawdown_pct is not None
            and portfolio.current_drawdown_pct >= p.portfolio_drawdown_limit_pct
        )
        if drawdown_breached:
            return decide(PortfolioRiskDecisionType.HALT, Decimal("0"), ["PORTFOLIO_DRAWDOWN_LIMIT_BREACHED"])

        # 4. Daily / weekly loss limits.
        daily_breached = (
            portfolio.daily_realized_pnl_pct is not None
            and -portfolio.daily_realized_pnl_pct >= p.daily_loss_limit_pct
        )
        if daily_breached:
            return decide(PortfolioRiskDecisionType.HALT, Decimal("0"), ["DAILY_LOSS_LIMIT_EXCEEDED"])
        weekly_breached = (
            portfolio.weekly_realized_pnl_pct is not None
            and -portfolio.weekly_realized_pnl_pct >= p.weekly_loss_limit_pct
        )
        if weekly_breached:
            return decide(PortfolioRiskDecisionType.HALT, Decimal("0"), ["WEEKLY_LOSS_LIMIT_EXCEEDED"])

        reasons: List[str] = []

        # 5. Stale-data / low-liquidity / evidence blocks — outright REJECT (candidate-
        # specific, not portfolio-wide, so REJECT rather than HALT).
        if context.is_stale_data:
            reasons.append("STALE_DATA_BLOCK")
        if context.is_low_liquidity:
            reasons.append("LOW_LIQUIDITY_BLOCK")
        if not context.evidence_actionable:
            reasons.append("EVIDENCE_BLOCK_NOT_ACTIONABLE")
        if reasons:
            return decide(PortfolioRiskDecisionType.REJECT, Decimal("0"), reasons)

        # 6. Max simultaneous positions.
        if portfolio.open_position_count >= p.max_simultaneous_positions:
            return decide(PortfolioRiskDecisionType.REJECT, Decimal("0"), ["MAX_SIMULTANEOUS_POSITIONS_REACHED"])

        approved_risk = requested_risk_pct
        reduce_reasons: List[str] = []

        # 7. Per-candidate cap.
        if approved_risk > p.max_risk_per_candidate_pct:
            approved_risk = p.max_risk_per_candidate_pct
            reduce_reasons.append("MAX_RISK_PER_CANDIDATE_APPLIED")

        # 8. Total open risk cap.
        open_risk = portfolio.open_risk_pct or Decimal("0")
        remaining_total = p.max_total_open_risk_pct - open_risk
        if remaining_total <= Decimal("0"):
            return decide(PortfolioRiskDecisionType.REJECT, Decimal("0"), ["MAX_TOTAL_OPEN_RISK_REACHED"])
        if approved_risk > remaining_total:
            approved_risk = remaining_total
            reduce_reasons.append("MAX_TOTAL_OPEN_RISK_APPLIED")

        # 9. Single-asset exposure cap.
        current_symbol_exposure = portfolio.positions_by_symbol.get(candidate.symbol, Decimal("0"))
        remaining_symbol = p.max_single_asset_exposure_pct - current_symbol_exposure
        if remaining_symbol <= Decimal("0"):
            return decide(PortfolioRiskDecisionType.REJECT, Decimal("0"), ["MAX_SINGLE_ASSET_EXPOSURE_REACHED"])
        if approved_risk > remaining_symbol:
            approved_risk = remaining_symbol
            reduce_reasons.append("MAX_SINGLE_ASSET_EXPOSURE_APPLIED")

        # 10. Correlated-exposure cap: sum exposure across symbols whose |correlation| with the
        # candidate's symbol meets the threshold. A missing correlation snapshot for a held
        # symbol is treated as "assume correlated" (conservative), never as zero.
        correlated_exposure = _correlated_exposure(
            candidate.symbol, portfolio, context.correlation_snapshots, p.correlated_threshold,
        )
        remaining_correlated = p.max_correlated_exposure_pct - correlated_exposure
        if remaining_correlated <= Decimal("0"):
            return decide(PortfolioRiskDecisionType.REJECT, Decimal("0"), ["MAX_CORRELATED_EXPOSURE_REACHED"])
        if approved_risk > remaining_correlated:
            approved_risk = remaining_correlated
            reduce_reasons.append("MAX_CORRELATED_EXPOSURE_APPLIED")

        if approved_risk <= Decimal("0"):
            return decide(
                PortfolioRiskDecisionType.REJECT, Decimal("0"), reduce_reasons or ["NO_RISK_BUDGET_REMAINING"],
            )

        if reduce_reasons:
            return decide(PortfolioRiskDecisionType.REDUCE, approved_risk, reduce_reasons)
        return decide(PortfolioRiskDecisionType.APPROVE, approved_risk, ["WITHIN_ALL_PORTFOLIO_RISK_LIMITS"])


def _correlated_exposure(
    symbol: str, portfolio: PortfolioSnapshot, snapshots: List[CorrelationSnapshot], threshold: Decimal,
) -> Decimal:
    snapshot_by_pair: Dict[FrozenSet[str], Optional[Decimal]] = {}
    for s in snapshots:
        snapshot_by_pair[frozenset({s.symbol_a, s.symbol_b})] = s.correlation

    total = Decimal("0")
    for held_symbol, exposure in portfolio.positions_by_symbol.items():
        if held_symbol == symbol:
            continue
        pair_key = frozenset({symbol, held_symbol})
        correlation = snapshot_by_pair.get(pair_key)
        # Missing snapshot -> conservative "assume correlated" (Section 9.4 / Section 11:
        # never treat missing correlation as zero/uncorrelated).
        if correlation is None or abs(correlation) >= threshold:
            total += exposure
    return total
