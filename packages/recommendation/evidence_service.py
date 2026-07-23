"""Strategy evidence registry and approval policy (out-of-sample proof gate).

Only an APPROVED strategy may back a user-facing TradeProposal in normal mode (see
`proposal_validator.check_candidate_gates`). The registry ships EMPTY: no walk-forward
backtest has produced committed evidence for any agent/strategy in this repository yet
(see docs/review/FINDINGS_REGISTER.md F-07, "STRATEGY QUALITY NOT PROVEN"). Every lookup
against an unregistered strategy honestly returns INSUFFICIENT -- never a fabricated or
assumed-good evidence record.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from packages.recommendation.config import RecommendationConfig, recommendation_config
from packages.recommendation.models import EvidenceStatus, StrategyEvidence


class EvidenceRegistry:
    def __init__(self) -> None:
        self._by_key: Dict[Tuple[str, str], StrategyEvidence] = {}

    def register(self, evidence: StrategyEvidence) -> None:
        self._by_key[(evidence.strategy_name, evidence.strategy_version)] = evidence

    def lookup(self, strategy_name: str, strategy_version: str) -> Optional[StrategyEvidence]:
        return self._by_key.get((strategy_name, strategy_version))

    def clear(self) -> None:
        self._by_key.clear()

    def __len__(self) -> int:
        return len(self._by_key)


evidence_registry = EvidenceRegistry()


def evaluate_approval(
    evidence: StrategyEvidence,
    config: RecommendationConfig = recommendation_config,
    now: Optional[datetime] = None,
) -> Tuple[EvidenceStatus, List[str]]:
    """Re-derives EvidenceStatus from the raw OOS metrics + policy thresholds every time
    (never trusts a cached status blindly), so a strategy that was APPROVED under an old,
    looser policy is re-evaluated correctly against the current one.
    """
    eval_time = now or datetime.now(timezone.utc)

    has_core_metrics = (
        evidence.out_of_sample_trades > 0
        and evidence.profit_factor is not None
        and evidence.sharpe is not None
        and evidence.maximum_drawdown_pct is not None
    )
    if not has_core_metrics:
        return EvidenceStatus.INSUFFICIENT, ["NO_OOS_METRICS_RECORDED"]
    # Narrow Optional[Decimal] -> Decimal for the type checker; has_core_metrics already
    # proved these are populated above.
    assert evidence.profit_factor is not None
    assert evidence.sharpe is not None
    assert evidence.maximum_drawdown_pct is not None

    if (eval_time - evidence.created_at).days > config.evidence_max_age_days:
        return EvidenceStatus.STALE, ["EVIDENCE_OLDER_THAN_MAX_AGE"]

    reasons: List[str] = []
    if evidence.out_of_sample_trades < config.evidence_min_oos_trades:
        reasons.append("INSUFFICIENT_OOS_TRADE_COUNT")
    if evidence.walk_forward_windows < config.evidence_min_walk_forward_windows:
        reasons.append("INSUFFICIENT_WALK_FORWARD_WINDOWS")
    if evidence.profit_factor < config.evidence_min_profit_factor:
        reasons.append("PROFIT_FACTOR_BELOW_THRESHOLD")
    if evidence.sharpe < config.evidence_min_sharpe:
        reasons.append("SHARPE_BELOW_THRESHOLD")
    if evidence.maximum_drawdown_pct > config.evidence_max_drawdown_pct:
        reasons.append("MAX_DRAWDOWN_EXCEEDS_LIMIT")
    if evidence.expectancy_bps is not None and evidence.expectancy_bps <= Decimal("0"):
        reasons.append("NON_POSITIVE_EXPECTANCY")

    if not reasons:
        return EvidenceStatus.APPROVED, []

    is_unprofitable = (evidence.expectancy_bps is not None and evidence.expectancy_bps <= Decimal("0")) or (
        evidence.profit_factor < Decimal("1.0")
    )
    if is_unprofitable:
        return EvidenceStatus.REJECTED, reasons

    # Positive-looking but short of one or more hard gates (e.g. too few OOS trades, or
    # too few walk-forward windows) -- kept visible for internal research, not user-facing.
    return EvidenceStatus.RESEARCH_ONLY, reasons


class EvidenceService:
    def __init__(
        self,
        registry: EvidenceRegistry = evidence_registry,
        config: RecommendationConfig = recommendation_config,
    ) -> None:
        self._registry = registry
        self._config = config

    def get_evidence(
        self,
        strategy_name: str,
        strategy_version: str,
        config_hash: str,
        feature_version: str,
        now: Optional[datetime] = None,
    ) -> StrategyEvidence:
        eval_time = now or datetime.now(timezone.utc)
        stored = self._registry.lookup(strategy_name, strategy_version)
        if stored is None:
            return StrategyEvidence(
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                model_version="none",
                feature_version=feature_version,
                config_hash=config_hash,
                status=EvidenceStatus.INSUFFICIENT,
                reason_codes=["NO_EVIDENCE_RECORDED"],
                created_at=eval_time,
            )
        status, reasons = evaluate_approval(stored, self._config, eval_time)
        if status == stored.status and reasons == stored.reason_codes:
            return stored
        return stored.model_copy(update={"status": status, "reason_codes": reasons})


evidence_service = EvidenceService()
