"""Phase 6: Portfolio Risk Governor — every decision must be exactly one of APPROVE/REDUCE/
REJECT/HALT, missing state must be conservative, and correlation/loss/drawdown limits must
actually bind."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from packages.candidates.models import CandidateStatus, TradeCandidate
from packages.domain.entities import CorrelationSnapshot
from packages.domain.enums import PortfolioRiskDecisionType
from packages.ports.interfaces import PortfolioSnapshot
from packages.risk.portfolio_governor import (
    BaselinePortfolioRiskGovernor,
    PortfolioRiskPolicy,
    RiskEvaluationContext,
)


def _candidate(symbol: str = "BTC/USDT") -> TradeCandidate:
    return TradeCandidate(
        session_id=uuid4(), symbol=symbol, timeframe="1h",
        decision_timestamp=datetime.now(timezone.utc), direction="LONG",
        agent_source="trend_agent_v1", agent_confidence=Decimal("0.75"),
        supporting_agents=["trend_agent_v1"], opposing_agents=[],
        consensus_score=Decimal("0.75"), critic_result="trend_agent_v1:APPROVED",
        allocator_result="TRADE_INTENT_CREATED", strategy_name="baseline", strategy_version="1.0.0",
        strategy_config_hash="hash1", market_regime="TREND_UP", feature_snapshot={},
        entry_reference=Decimal("50000"), estimated_fee_bps=Decimal("10"),
        estimated_spread_bps=Decimal("2"), estimated_slippage_bps=Decimal("5"),
        status=CandidateStatus.PROPOSED,
    )


def _clean_portfolio(**overrides) -> PortfolioSnapshot:
    base = dict(
        available=True, nav=Decimal("100000"), open_risk_pct=Decimal("0"), open_position_count=0,
        daily_realized_pnl_pct=Decimal("0"), weekly_realized_pnl_pct=Decimal("0"),
        current_drawdown_pct=Decimal("0"), kill_switch_active=False, positions_by_symbol={},
    )
    base.update(overrides)
    return PortfolioSnapshot(**base)


def _clean_context(**overrides) -> RiskEvaluationContext:
    base = dict(evidence_actionable=True)
    base.update(overrides)
    return RiskEvaluationContext(**base)


def test_within_all_limits_approves_full_requested_risk() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("0.25"), _clean_portfolio(), _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.APPROVE
    assert decision.approved_risk_pct == Decimal("0.25")


def test_missing_portfolio_state_halts_conservatively() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("0.25"), PortfolioSnapshot(available=False), _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.HALT
    assert decision.approved_risk_pct == Decimal("0")
    assert "PORTFOLIO_STATE_UNAVAILABLE" in decision.reason_codes


def test_kill_switch_halts_regardless_of_everything_else() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("0.1"), _clean_portfolio(kill_switch_active=True), _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.HALT
    assert "KILL_SWITCH_ACTIVE" in decision.reason_codes


def test_drawdown_breaker_halts() -> None:
    gov = BaselinePortfolioRiskGovernor()
    portfolio = _clean_portfolio(current_drawdown_pct=Decimal("9.0"))  # > 8.0 default limit
    decision = gov.evaluate(_candidate(), Decimal("0.1"), portfolio, _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.HALT
    assert "PORTFOLIO_DRAWDOWN_LIMIT_BREACHED" in decision.reason_codes


def test_daily_loss_limit_halts() -> None:
    gov = BaselinePortfolioRiskGovernor()
    portfolio = _clean_portfolio(daily_realized_pnl_pct=Decimal("-2.0"))  # -2% loss > 1.5% limit
    decision = gov.evaluate(_candidate(), Decimal("0.1"), portfolio, _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.HALT
    assert "DAILY_LOSS_LIMIT_EXCEEDED" in decision.reason_codes


def test_weekly_loss_limit_halts() -> None:
    gov = BaselinePortfolioRiskGovernor()
    portfolio = _clean_portfolio(weekly_realized_pnl_pct=Decimal("-5.0"))  # > 4.0 default limit
    decision = gov.evaluate(_candidate(), Decimal("0.1"), portfolio, _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.HALT
    assert "WEEKLY_LOSS_LIMIT_EXCEEDED" in decision.reason_codes


def test_max_risk_per_candidate_reduces() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("1.0"), _clean_portfolio(), _clean_context())  # way above 0.25 cap
    assert decision.decision == PortfolioRiskDecisionType.REDUCE
    assert decision.approved_risk_pct == Decimal("0.25")
    assert "MAX_RISK_PER_CANDIDATE_APPLIED" in decision.reason_codes


def test_max_total_open_risk_rejects_when_already_full() -> None:
    gov = BaselinePortfolioRiskGovernor()
    portfolio = _clean_portfolio(open_risk_pct=Decimal("2.0"))  # already at the 2.0 cap
    decision = gov.evaluate(_candidate(), Decimal("0.1"), portfolio, _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert "MAX_TOTAL_OPEN_RISK_REACHED" in decision.reason_codes


def test_max_simultaneous_positions_rejects() -> None:
    gov = BaselinePortfolioRiskGovernor()
    portfolio = _clean_portfolio(open_position_count=5)  # at the default cap of 5
    decision = gov.evaluate(_candidate(), Decimal("0.1"), portfolio, _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert "MAX_SIMULTANEOUS_POSITIONS_REACHED" in decision.reason_codes


def test_stale_data_blocks_with_reject() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("0.1"), _clean_portfolio(), _clean_context(is_stale_data=True))
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert "STALE_DATA_BLOCK" in decision.reason_codes


def test_low_liquidity_blocks_with_reject() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("0.1"), _clean_portfolio(), _clean_context(is_low_liquidity=True))
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert "LOW_LIQUIDITY_BLOCK" in decision.reason_codes


def test_evidence_not_actionable_blocks_with_reject() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("0.1"), _clean_portfolio(), _clean_context(evidence_actionable=False))
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert "EVIDENCE_BLOCK_NOT_ACTIONABLE" in decision.reason_codes


def test_correlated_exposure_limit_rejects() -> None:
    gov = BaselinePortfolioRiskGovernor(policy=PortfolioRiskPolicy(max_correlated_exposure_pct=Decimal("5.0")))
    portfolio = _clean_portfolio(positions_by_symbol={"ETH/USDT": Decimal("10.0")})
    snapshot = CorrelationSnapshot(
        window_config_version="corr_v1", symbol_a="BTC/USDT", symbol_b="ETH/USDT", timeframe="1h",
        window_bars=90, sample_count=90, correlation=Decimal("0.9"),
    )
    context = _clean_context(correlation_snapshots=[snapshot])
    decision = gov.evaluate(_candidate("BTC/USDT"), Decimal("0.1"), portfolio, context)
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert "MAX_CORRELATED_EXPOSURE_REACHED" in decision.reason_codes


def test_missing_correlation_snapshot_is_treated_as_correlated_not_zero() -> None:
    """No snapshot for a held symbol -> conservative assume-correlated, so it still counts
    toward the correlated-exposure cap (never silently treated as uncorrelated)."""
    gov = BaselinePortfolioRiskGovernor(policy=PortfolioRiskPolicy(max_correlated_exposure_pct=Decimal("5.0")))
    portfolio = _clean_portfolio(positions_by_symbol={"ETH/USDT": Decimal("10.0")})
    context = _clean_context(correlation_snapshots=[])  # no snapshot at all for BTC/ETH
    decision = gov.evaluate(_candidate("BTC/USDT"), Decimal("0.1"), portfolio, context)
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert "MAX_CORRELATED_EXPOSURE_REACHED" in decision.reason_codes


def test_low_correlation_does_not_count_toward_correlated_cap() -> None:
    gov = BaselinePortfolioRiskGovernor(policy=PortfolioRiskPolicy(max_correlated_exposure_pct=Decimal("5.0")))
    portfolio = _clean_portfolio(positions_by_symbol={"ETH/USDT": Decimal("10.0")})
    snapshot = CorrelationSnapshot(
        window_config_version="corr_v1", symbol_a="BTC/USDT", symbol_b="ETH/USDT", timeframe="1h",
        window_bars=90, sample_count=90, correlation=Decimal("0.1"),  # well below the 0.7 threshold
    )
    context = _clean_context(correlation_snapshots=[snapshot])
    decision = gov.evaluate(_candidate("BTC/USDT"), Decimal("0.1"), portfolio, context)
    assert decision.decision == PortfolioRiskDecisionType.APPROVE


def test_single_asset_exposure_cap_reduces() -> None:
    gov = BaselinePortfolioRiskGovernor(policy=PortfolioRiskPolicy(max_single_asset_exposure_pct=Decimal("0.3")))
    portfolio = _clean_portfolio(positions_by_symbol={"BTC/USDT": Decimal("0.2")})
    decision = gov.evaluate(_candidate("BTC/USDT"), Decimal("0.25"), portfolio, _clean_context())
    assert decision.decision == PortfolioRiskDecisionType.REDUCE
    assert decision.approved_risk_pct == Decimal("0.1")  # 0.3 - 0.2 remaining
    assert "MAX_SINGLE_ASSET_EXPOSURE_APPLIED" in decision.reason_codes


def test_every_decision_carries_policy_version_and_snapshot_reference() -> None:
    gov = BaselinePortfolioRiskGovernor()
    decision = gov.evaluate(_candidate(), Decimal("0.1"), _clean_portfolio(), _clean_context())
    assert decision.policy_version == "portfolio_risk_v1"
    assert decision.candidate_id is not None
