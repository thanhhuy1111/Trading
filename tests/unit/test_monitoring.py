"""Phase 11: monitoring metrics, drift detection, and conservative automatic evidence
lifecycle actions - never an automatic promotion, never a silent kill-switch reset."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from packages.domain.enums import DriftSeverity
from packages.evidence.audit import EvidenceAuditLog
from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus
from packages.evidence.store import EvidenceStore
from packages.monitoring.drift import BaselineDriftService
from packages.monitoring.evidence_lifecycle import (
    EVIDENCE_AUTO_DEGRADED,
    EVIDENCE_AUTO_DISABLED,
    KillSwitch,
    apply_drift_action,
    should_disable_new_proposals,
)
from packages.monitoring.metrics import ALL_METRIC_NAMES, CANDIDATES_GENERATED_TOTAL, EVIDENCE_MISSING_TOTAL
from packages.monitoring.service import BaselineMonitoringService

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_exactly_twenty_named_metrics() -> None:
    assert len(ALL_METRIC_NAMES) == 20


def test_record_metric_and_total() -> None:
    service = BaselineMonitoringService(EvidenceStore())
    service.record_metric(CANDIDATES_GENERATED_TOTAL, Decimal("1"))
    service.record_metric(CANDIDATES_GENERATED_TOTAL, Decimal("1"))
    service.record_metric(EVIDENCE_MISSING_TOTAL, Decimal("1"))
    assert service.metrics_store.total(CANDIDATES_GENERATED_TOTAL) == Decimal("2")
    assert service.metrics_store.total(EVIDENCE_MISSING_TOTAL) == Decimal("1")


def test_unregistered_metric_name_is_still_recorded_but_flagged() -> None:
    service = BaselineMonitoringService(EvidenceStore())
    service.record_metric("totally_made_up_metric", Decimal("1"))
    samples = service.metrics_store.samples_for("totally_made_up_metric")
    assert samples[0].tags.get("unregistered_metric_name") == "true"


def test_current_readiness_empty_registry() -> None:
    service = BaselineMonitoringService(EvidenceStore())
    readiness = service.current_readiness()
    assert readiness.evidence_readiness.value == "EMPTY_REGISTRY"
    assert readiness.live_readiness.value == "DISABLED"


def test_drift_missing_data_is_flagged_not_silently_none() -> None:
    result = BaselineDriftService().assess("model:lr_v1", "accuracy", None, Decimal("0.6"))
    assert result.severity == DriftSeverity.NONE
    assert "INSUFFICIENT_DATA_FOR_DRIFT_ASSESSMENT" in result.reason_codes
    assert result.recommended_action == "COLLECT_MORE_BASELINE_DATA"


@pytest.mark.parametrize("baseline,current,expected", [
    (Decimal("100"), Decimal("105"), DriftSeverity.NONE),
    (Decimal("100"), Decimal("115"), DriftSeverity.LOW),
    (Decimal("100"), Decimal("130"), DriftSeverity.MODERATE),
    (Decimal("100"), Decimal("160"), DriftSeverity.SEVERE),
])
def test_drift_severity_thresholds(baseline, current, expected) -> None:
    result = BaselineDriftService().assess("feature:rsi_14", "mean", baseline, current)
    assert result.severity == expected


def _key() -> EvidenceKey:
    return EvidenceKey(
        strategy_name="baseline", strategy_version="1.0.0", symbol="BTC/USDT", timeframe="1h",
        model_type="PASS_THROUGH", model_version="n/a", feature_version="standard_v1",
        label_version="meta_label_v1", dataset_checksum="n/a", gate_version="gate_v1",
        config_hash="hash1", code_commit="n/a",
    )


def _record(status: EvidenceStatus) -> EvidenceRecord:
    return EvidenceRecord(key=_key(), status=status, generated_at=T0, total_oos_trades=50)


def test_moderate_drift_degrades_approved_evidence() -> None:
    log = EvidenceAuditLog()
    store = EvidenceStore(audit_log=log)
    store.register(_record(EvidenceStatus.ASSET_SPECIFIC_APPROVED))
    drift = BaselineDriftService().assess("evidence:baseline/BTC", "calibration", Decimal("100"), Decimal("130"))

    new_status = apply_drift_action(store, _key(), drift, audit_log=log)
    assert new_status == EvidenceStatus.DEGRADED
    assert store.lookup(_key()).status == EvidenceStatus.DEGRADED
    assert any(e.event_type == EVIDENCE_AUTO_DEGRADED for e in log.events)


def test_severe_drift_disables_evidence_directly_from_approved() -> None:
    log = EvidenceAuditLog()
    store = EvidenceStore(audit_log=log)
    store.register(_record(EvidenceStatus.UNIVERSAL_APPROVED))
    drift = BaselineDriftService().assess("evidence:baseline/BTC", "calibration", Decimal("100"), Decimal("170"))

    new_status = apply_drift_action(store, _key(), drift, audit_log=log)
    assert new_status == EvidenceStatus.DISABLED
    assert any(e.event_type == EVIDENCE_AUTO_DISABLED for e in log.events)


def test_low_drift_takes_no_action() -> None:
    store = EvidenceStore()
    store.register(_record(EvidenceStatus.ASSET_SPECIFIC_APPROVED))
    drift = BaselineDriftService().assess("evidence:baseline/BTC", "calibration", Decimal("100"), Decimal("105"))
    assert apply_drift_action(store, _key(), drift) is None
    assert store.lookup(_key()).status == EvidenceStatus.ASSET_SPECIFIC_APPROVED


def test_drift_action_never_touches_rejected_or_research_only_records() -> None:
    store = EvidenceStore()
    store.register(_record(EvidenceStatus.REJECTED))
    severe = BaselineDriftService().assess("x", "y", Decimal("100"), Decimal("200"))
    assert apply_drift_action(store, _key(), severe) is None
    assert store.lookup(_key()).status == EvidenceStatus.REJECTED


def test_drift_action_missing_evidence_record_is_a_no_op() -> None:
    store = EvidenceStore()
    drift = BaselineDriftService().assess("x", "y", Decimal("100"), Decimal("200"))
    assert apply_drift_action(store, _key(), drift) is None


def test_kill_switch_can_only_be_reset_by_a_named_actor() -> None:
    switch = KillSwitch()
    assert switch.is_active is False
    switch.trip("SEVERE_DRIFT_DETECTED")
    assert switch.is_active is True
    assert should_disable_new_proposals(switch) is True

    with pytest.raises(ValueError):
        switch.reset("")

    switch.reset("ops_lead_jane")
    assert switch.is_active is False
    assert switch.reason_codes == []
