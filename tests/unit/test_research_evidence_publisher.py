"""Unit tests for packages/research/evidence_publisher.py."""

import shutil
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from packages.recommendation.evidence_service import EvidenceRegistry
from packages.recommendation.models import EvidenceStatus
from packages.research.artifacts import ArtifactStore
from packages.research.config import ApprovalGateConfig
from packages.research.evidence_publisher import (
    build_strategy_evidence,
    compute_single_window_profit_share,
    evaluate_research_approval,
    publish_evidence,
)
from packages.research.models import CalibrationReport, EvaluationBreakdown, EvaluationMetrics, EvaluationReport

NOW = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)


def _strong_metrics(trade_count=250) -> EvaluationMetrics:
    return EvaluationMetrics(
        trade_count=trade_count,
        win_rate=Decimal("58.0"),
        net_pnl_bps=Decimal("5000.0"),
        average_net_return_bps=Decimal("20.0"),
        expectancy_bps=Decimal("20.0"),
        profit_factor=Decimal("1.45"),
        sharpe=Decimal("1.30"),
        sortino=Decimal("1.60"),
        calmar=Decimal("2.0"),
        max_drawdown_pct=Decimal("8.0"),
        turnover=Decimal(trade_count),
        total_fees_bps=Decimal("2200.0"),
        average_holding_minutes=Decimal("120.0"),
    )


def _window_breakdowns(profits):
    return [
        EvaluationBreakdown(
            dimension="window", key=f"fold_{i + 1}", metrics=EvaluationMetrics(trade_count=10, net_pnl_bps=p)
        )
        for i, p in enumerate(profits)
    ]


def _good_calibration() -> CalibrationReport:
    return CalibrationReport(
        method="platt", sample_size=300, brier_score=0.15, log_loss=0.45,
        expected_calibration_error=0.05, calibration_score=0.90, reliability_buckets=[],
    )


_UNSET = object()


def _evaluation_report(metrics=None, breakdowns=None, calibration=_UNSET, walk_forward_windows=4) -> EvaluationReport:
    return EvaluationReport(
        subject_name="logreg_v1", subject_type="MODEL", dataset_checksum="abc123",
        walk_forward_windows=walk_forward_windows, aggregate_metrics=metrics or _strong_metrics(),
        breakdowns=breakdowns if breakdowns is not None else _window_breakdowns([1000, 1200, 900, 1900]),
        calibration=_good_calibration() if calibration is _UNSET else calibration,
        created_at=NOW, code_commit="deadbeef", config_hash="cfg-hash",
    )


_APPROVAL_CONFIG = ApprovalGateConfig()


# --------------------------------------------------------------------------------------
# build_strategy_evidence
# --------------------------------------------------------------------------------------


def test_build_strategy_evidence_maps_fields():
    evaluation = _evaluation_report()
    evidence = build_strategy_evidence(
        evaluation, "multi_agent_consensus_pipeline", "1.0.0", "logreg_v1", "standard_v1", now=NOW
    )

    assert evidence.strategy_name == "multi_agent_consensus_pipeline"
    assert evidence.dataset_checksum == "abc123"
    assert evidence.out_of_sample_trades == 250
    assert evidence.profit_factor == Decimal("1.45")
    assert evidence.walk_forward_windows == 4
    assert evidence.status == EvidenceStatus.INSUFFICIENT  # pre-approval-check default
    assert "platt" in evidence.calibration_metrics


# --------------------------------------------------------------------------------------
# compute_single_window_profit_share
# --------------------------------------------------------------------------------------


def test_compute_single_window_profit_share_none_without_windows():
    evaluation = _evaluation_report(breakdowns=[])
    assert compute_single_window_profit_share(evaluation) is None


def test_compute_single_window_profit_share_ratio():
    evaluation = _evaluation_report(breakdowns=_window_breakdowns([100, 100, 700, 100]))
    share = compute_single_window_profit_share(evaluation)
    assert share == pytest.approx(Decimal("0.7"))


# --------------------------------------------------------------------------------------
# evaluate_research_approval
# --------------------------------------------------------------------------------------


def test_evaluate_research_approval_approves_strong_diversified_evidence():
    evaluation = _evaluation_report(breakdowns=_window_breakdowns([1000, 1200, 900, 1900]))
    evidence = build_strategy_evidence(evaluation, "pipeline", "1.0.0", "logreg_v1", "standard_v1", now=NOW)
    status, reasons = evaluate_research_approval(evidence, evaluation, _APPROVAL_CONFIG, now=NOW)
    assert status == EvidenceStatus.APPROVED
    assert reasons == []


def test_evaluate_research_approval_downgrades_when_profit_concentrated_in_one_window():
    # One window contributes the overwhelming majority of positive profit.
    evaluation = _evaluation_report(breakdowns=_window_breakdowns([50, 30, 20, 5000]))
    evidence = build_strategy_evidence(evaluation, "pipeline", "1.0.0", "logreg_v1", "standard_v1", now=NOW)
    status, reasons = evaluate_research_approval(evidence, evaluation, _APPROVAL_CONFIG, now=NOW)
    assert status == EvidenceStatus.RESEARCH_ONLY
    assert "PROFIT_CONCENTRATED_IN_SINGLE_WINDOW" in reasons


def test_evaluate_research_approval_downgrades_when_no_calibration_report():
    evaluation = _evaluation_report(calibration=None)
    evidence = build_strategy_evidence(evaluation, "pipeline", "1.0.0", "logreg_v1", "standard_v1", now=NOW)
    status, reasons = evaluate_research_approval(evidence, evaluation, _APPROVAL_CONFIG, now=NOW)
    assert status == EvidenceStatus.RESEARCH_ONLY
    assert "NO_CALIBRATION_REPORT" in reasons


def test_evaluate_research_approval_downgrades_when_calibration_too_low():
    poor_calibration = _good_calibration().model_copy(update={"calibration_score": 0.10})
    evaluation = _evaluation_report(calibration=poor_calibration)
    evidence = build_strategy_evidence(evaluation, "pipeline", "1.0.0", "logreg_v1", "standard_v1", now=NOW)
    status, reasons = evaluate_research_approval(evidence, evaluation, _APPROVAL_CONFIG, now=NOW)
    assert status == EvidenceStatus.RESEARCH_ONLY
    assert "CALIBRATION_BELOW_THRESHOLD" in reasons


def test_evaluate_research_approval_never_upgrades_a_rejected_result():
    weak_metrics = _strong_metrics(trade_count=5)  # far below evidence_min_oos_trades
    evaluation = _evaluation_report(metrics=weak_metrics)
    evidence = build_strategy_evidence(evaluation, "pipeline", "1.0.0", "logreg_v1", "standard_v1", now=NOW)
    status, reasons = evaluate_research_approval(evidence, evaluation, _APPROVAL_CONFIG, now=NOW)
    assert status in (EvidenceStatus.RESEARCH_ONLY, EvidenceStatus.INSUFFICIENT, EvidenceStatus.REJECTED)
    assert status != EvidenceStatus.APPROVED


# --------------------------------------------------------------------------------------
# publish_evidence
# --------------------------------------------------------------------------------------


@pytest.fixture
def tmp_artifact_store():
    tmp_dir = tempfile.mkdtemp(prefix="evidence_publisher_test_")
    yield ArtifactStore(root=tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_publish_evidence_registers_and_persists(tmp_artifact_store):
    registry = EvidenceRegistry()
    evaluation = _evaluation_report()

    evidence = publish_evidence(
        evaluation, "pipeline", "1.0.0", "logreg_v1", "standard_v1", _APPROVAL_CONFIG,
        registry=registry, store=tmp_artifact_store, now=NOW,
    )

    looked_up = registry.lookup("pipeline", "1.0.0")
    assert looked_up is not None
    assert looked_up.evidence_id == evidence.evidence_id
    assert looked_up.status == evidence.status

    from packages.recommendation.models import StrategyEvidence

    persisted = tmp_artifact_store.load_metadata("evidence", evidence.evidence_id, StrategyEvidence)
    assert persisted.evidence_id == evidence.evidence_id
