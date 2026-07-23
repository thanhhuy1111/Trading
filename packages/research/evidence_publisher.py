"""Turns a research EvaluationReport into a typed `StrategyEvidence` and registers it
into the EXISTING `packages.recommendation.evidence_service.evidence_registry` -- the
same registry `RecommendationService` / the chat `get_strategy_evidence` tool already
read from before this phase existed. This is the one place research results become
visible to the runtime recommendation pipeline; nothing else writes to that registry.

Approval status is decided in two layers, in order, and NEVER loosened to force APPROVED:

  1. `packages.recommendation.evidence_service.evaluate_approval` -- the EXISTING policy
     (OOS trade count, walk-forward window count, profit factor, Sharpe, max drawdown,
     non-positive expectancy, staleness). Reused as-is, not reimplemented.
  2. Two research-specific checks this module adds on top, which can only DOWNGRADE an
     APPROVED result to RESEARCH_ONLY, never upgrade a REJECTED/INSUFFICIENT/STALE one:
       - profit concentrated in a single walk-forward window
         (packages.research.config.ApprovalGateConfig.max_single_window_profit_share)
       - missing or below-threshold calibration
         (packages.research.config.ApprovalGateConfig.min_calibration_score)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from packages.recommendation.config import recommendation_config
from packages.recommendation.evidence_service import EvidenceRegistry, evaluate_approval, evidence_registry
from packages.recommendation.models import EvidenceStatus, StrategyEvidence
from packages.research.artifacts import ArtifactStore, artifact_store
from packages.research.config import ApprovalGateConfig
from packages.research.models import EvaluationReport


def compute_single_window_profit_share(evaluation: EvaluationReport) -> Optional[Decimal]:
    windows = [b for b in evaluation.breakdowns if b.dimension == "window"]
    if not windows:
        return None
    positive_profits = [b.metrics.net_pnl_bps for b in windows if b.metrics.net_pnl_bps and b.metrics.net_pnl_bps > 0]
    if not positive_profits:
        return None
    total_positive = sum(positive_profits, Decimal("0"))
    if total_positive <= 0:
        return None
    return max(positive_profits) / total_positive


def build_strategy_evidence(
    evaluation: EvaluationReport,
    strategy_name: str,
    strategy_version: str,
    model_version: str,
    feature_version: str,
    train_period: Optional[str] = None,
    validation_period: Optional[str] = None,
    test_period: Optional[str] = None,
    now: Optional[datetime] = None,
) -> StrategyEvidence:
    eval_time = now or datetime.now(timezone.utc)
    m = evaluation.aggregate_metrics

    calibration_metrics = None
    if evaluation.calibration is not None:
        calibration_metrics = (
            f"method={evaluation.calibration.method},"
            f"brier={evaluation.calibration.brier_score:.4f},"
            f"log_loss={evaluation.calibration.log_loss:.4f},"
            f"ece={evaluation.calibration.expected_calibration_error:.4f},"
            f"calibration_score={evaluation.calibration.calibration_score:.4f}"
        )

    return StrategyEvidence(
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        model_version=model_version,
        feature_version=feature_version,
        dataset_checksum=evaluation.dataset_checksum,
        config_hash=evaluation.config_hash,
        code_commit=evaluation.code_commit,
        train_period=train_period,
        validation_period=validation_period,
        test_period=test_period,
        walk_forward_windows=evaluation.walk_forward_windows,
        out_of_sample_trades=m.trade_count,
        net_pnl_pct=(m.net_pnl_bps / Decimal("100")) if m.net_pnl_bps is not None else None,
        profit_factor=m.profit_factor,
        sharpe=m.sharpe,
        sortino=m.sortino,
        calmar=m.calmar,
        maximum_drawdown_pct=m.max_drawdown_pct,
        expectancy_bps=m.expectancy_bps,
        turnover=m.turnover,
        estimated_fees_bps=m.total_fees_bps,
        calibration_metrics=calibration_metrics,
        status=EvidenceStatus.INSUFFICIENT,
        created_at=eval_time,
    )


def evaluate_research_approval(
    evidence: StrategyEvidence,
    evaluation: EvaluationReport,
    research_approval_config: ApprovalGateConfig,
    now: Optional[datetime] = None,
) -> tuple:
    """Returns (status, reason_codes). Layer 1 (existing policy) can produce any status;
    layer 2 (below) can only downgrade an APPROVED result, never upgrade any other.
    """
    status, reasons = evaluate_approval(evidence, recommendation_config, now)
    reasons = list(reasons)

    if status != EvidenceStatus.APPROVED:
        return status, reasons

    extra_reasons: List[str] = []
    window_share = compute_single_window_profit_share(evaluation)
    if window_share is not None and window_share > research_approval_config.max_single_window_profit_share:
        extra_reasons.append("PROFIT_CONCENTRATED_IN_SINGLE_WINDOW")

    if evaluation.calibration is None:
        extra_reasons.append("NO_CALIBRATION_REPORT")
    elif Decimal(str(evaluation.calibration.calibration_score)) < research_approval_config.min_calibration_score:
        extra_reasons.append("CALIBRATION_BELOW_THRESHOLD")

    if extra_reasons:
        return EvidenceStatus.RESEARCH_ONLY, reasons + extra_reasons
    return EvidenceStatus.APPROVED, reasons


def publish_evidence(
    evaluation: EvaluationReport,
    strategy_name: str,
    strategy_version: str,
    model_version: str,
    feature_version: str,
    research_approval_config: ApprovalGateConfig,
    train_period: Optional[str] = None,
    validation_period: Optional[str] = None,
    test_period: Optional[str] = None,
    registry: EvidenceRegistry = evidence_registry,
    store: ArtifactStore = artifact_store,
    now: Optional[datetime] = None,
) -> StrategyEvidence:
    """Builds, evaluates, registers (into the runtime EvidenceRegistry), and persists
    (as an audit-trail artifact) the StrategyEvidence for one evaluated subject. This is
    the ONLY function in this package that writes to the runtime evidence_registry.
    """
    eval_time = now or datetime.now(timezone.utc)
    draft = build_strategy_evidence(
        evaluation, strategy_name, strategy_version, model_version, feature_version,
        train_period, validation_period, test_period, eval_time,
    )
    status, reasons = evaluate_research_approval(draft, evaluation, research_approval_config, eval_time)
    final_evidence = draft.model_copy(update={"status": status, "reason_codes": reasons})

    registry.register(final_evidence)
    store.save_metadata("evidence", final_evidence.evidence_id, final_evidence)
    return final_evidence
