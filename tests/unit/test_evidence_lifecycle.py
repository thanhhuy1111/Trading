"""Phase 5: full evidence lifecycle — typed lookup results (MATCH/MISMATCH/MISSING/STALE/
DISABLED) and audit logging for every lifecycle event."""

from datetime import datetime, timedelta, timezone

from packages.domain.enums import EvidenceLookupResult
from packages.evidence.audit import (
    EVIDENCE_CREATED,
    EVIDENCE_DISABLED,
    EVIDENCE_STALED,
    LOOKUP_REJECTED,
    EvidenceAuditLog,
)
from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus
from packages.evidence.store import EvidenceStore


def _key(**overrides) -> EvidenceKey:
    base = dict(
        strategy_name="baseline", strategy_version="1.0.0", symbol="BTC/USDT", timeframe="1d",
        model_type="RULE_BASED_MULTI_AGENT", model_version="n/a", feature_version="standard_v1",
        label_version="meta_label_v1", dataset_checksum="abc123", gate_version="gate_v1",
        config_hash="hash1", code_commit="deadbeef",
    )
    base.update(overrides)
    return EvidenceKey(**base)


def _record(key: EvidenceKey, status: EvidenceStatus, **overrides) -> EvidenceRecord:
    base = dict(key=key, status=status, generated_at=datetime.now(timezone.utc), total_oos_trades=50)
    base.update(overrides)
    return EvidenceRecord(**base)


def test_match_result_for_exact_registered_key() -> None:
    log = EvidenceAuditLog()
    store = EvidenceStore(audit_log=log)
    key = _key()
    store.register(_record(key, EvidenceStatus.ASSET_SPECIFIC_APPROVED))

    outcome = store.lookup_with_result(key)
    assert outcome.result == EvidenceLookupResult.MATCH
    assert outcome.record is not None
    assert any(e.event_type == EVIDENCE_CREATED for e in log.events)


def test_missing_result_when_nothing_registered_at_all() -> None:
    store = EvidenceStore(audit_log=EvidenceAuditLog())
    outcome = store.lookup_with_result(_key(symbol="DOGE/USDT"))
    assert outcome.result == EvidenceLookupResult.MISSING


def test_mismatch_result_when_near_key_exists_but_not_exact() -> None:
    log = EvidenceAuditLog()
    store = EvidenceStore(audit_log=log)
    store.register(_record(_key(model_version="v1"), EvidenceStatus.ASSET_SPECIFIC_APPROVED))

    outcome = store.lookup_with_result(_key(model_version="v2"))  # same symbol/tf/strategy, different model
    assert outcome.result == EvidenceLookupResult.MISMATCH
    assert any(e.event_type == LOOKUP_REJECTED for e in log.events)


def test_symbol_mismatch_is_missing_not_mismatch() -> None:
    """A wholly different symbol has no "near" relationship — MISSING, not MISMATCH."""
    store = EvidenceStore(audit_log=EvidenceAuditLog())
    store.register(_record(_key(symbol="BTC/USDT"), EvidenceStatus.ASSET_SPECIFIC_APPROVED))
    outcome = store.lookup_with_result(_key(symbol="ETH/USDT"))
    assert outcome.result == EvidenceLookupResult.MISSING


def test_stale_result_and_audit_event() -> None:
    log = EvidenceAuditLog()
    store = EvidenceStore(audit_log=log)
    key = _key()
    expired = _record(
        key, EvidenceStatus.UNIVERSAL_APPROVED,
        generated_at=datetime.now(timezone.utc) - timedelta(days=60),
        expires_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    store.register(expired)

    outcome = store.lookup_with_result(key)
    assert outcome.result == EvidenceLookupResult.STALE
    assert any(e.event_type == EVIDENCE_STALED for e in log.events)
    assert any(e.event_type == LOOKUP_REJECTED for e in log.events)


def test_disabled_result_and_audit_event() -> None:
    log = EvidenceAuditLog()
    store = EvidenceStore(audit_log=log)
    key = _key()
    store.register(_record(key, EvidenceStatus.DISABLED))

    outcome = store.lookup_with_result(key)
    assert outcome.result == EvidenceLookupResult.DISABLED
    assert any(e.event_type == EVIDENCE_DISABLED for e in log.events)


def test_registering_same_key_twice_logs_updated_not_created_twice() -> None:
    log = EvidenceAuditLog()
    store = EvidenceStore(audit_log=log)
    key = _key()
    store.register(_record(key, EvidenceStatus.RESEARCH_ONLY))
    store.register(_record(key, EvidenceStatus.REJECTED))

    created_events = log.events_by_type(EVIDENCE_CREATED)
    updated_events = log.events_by_type("evidence_updated")
    assert len(created_events) == 1
    assert len(updated_events) == 1
