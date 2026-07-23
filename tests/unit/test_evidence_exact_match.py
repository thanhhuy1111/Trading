"""Phase 3: evidence lookup must be exact-match only — no BTC<->ETH, no 1h<->4h, no
model-version fallback, ever."""

from datetime import datetime, timedelta, timezone

from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus
from packages.evidence.store import EvidenceStore


def _key(**overrides) -> EvidenceKey:
    base = dict(
        strategy_name="baseline",
        strategy_version="1.0.0",
        symbol="BTC/USDT",
        timeframe="1d",
        model_type="RULE_BASED_MULTI_AGENT",
        model_version="n/a",
        feature_version="standard_v1",
        label_version="meta_label_v1",
        dataset_checksum="abc123",
        gate_version="gate_v1",
        config_hash="hash1",
        code_commit="deadbeef",
    )
    base.update(overrides)
    return EvidenceKey(**base)


def _approved_record(key: EvidenceKey) -> EvidenceRecord:
    return EvidenceRecord(
        key=key,
        status=EvidenceStatus.UNIVERSAL_APPROVED,
        generated_at=datetime.now(timezone.utc),
        total_oos_trades=100,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )


def test_exact_match_returns_registered_record() -> None:
    store = EvidenceStore()
    key = _key()
    store.register(_approved_record(key))
    assert store.lookup(key) is not None
    assert store.is_actionable(key) is True


def test_symbol_mismatch_never_falls_back() -> None:
    store = EvidenceStore()
    store.register(_approved_record(_key(symbol="BTC/USDT")))
    eth_key = _key(symbol="ETH/USDT")
    assert store.lookup(eth_key) is None
    assert store.is_actionable(eth_key) is False


def test_timeframe_mismatch_never_falls_back() -> None:
    store = EvidenceStore()
    store.register(_approved_record(_key(timeframe="1h")))
    assert store.lookup(_key(timeframe="4h")) is None
    assert store.is_actionable(_key(timeframe="4h")) is False


def test_model_version_mismatch_never_falls_back() -> None:
    store = EvidenceStore()
    store.register(_approved_record(_key(model_version="v1")))
    assert store.lookup(_key(model_version="v2")) is None


def test_config_hash_mismatch_never_falls_back() -> None:
    """Same symbol/timeframe/strategy_name but a different parameter set (config_hash) must
    not inherit another config's evidence — this is the case a naive (symbol, strategy_name)
    lookup would incorrectly conflate."""
    store = EvidenceStore()
    store.register(_approved_record(_key(config_hash="hash1")))
    assert store.lookup(_key(config_hash="hash2")) is None


def test_gate_version_mismatch_never_falls_back() -> None:
    """Approval under an old, looser gate must not be reused once the gate tightens."""
    store = EvidenceStore()
    store.register(_approved_record(_key(gate_version="gate_v1")))
    assert store.lookup(_key(gate_version="gate_v2")) is None


def test_expired_evidence_reports_stale_not_approved() -> None:
    store = EvidenceStore()
    key = _key()
    expired = EvidenceRecord(
        key=key,
        status=EvidenceStatus.UNIVERSAL_APPROVED,
        generated_at=datetime.now(timezone.utc) - timedelta(days=60),
        total_oos_trades=100,
        expires_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    store.register(expired)
    result = store.lookup(key)
    assert result is not None
    assert result.status == EvidenceStatus.STALE
    assert store.is_actionable(key) is False


def test_rejected_and_missing_are_both_non_actionable() -> None:
    store = EvidenceStore()
    rejected_key = _key(config_hash="rejected_one")
    store.register(EvidenceRecord(
        key=rejected_key, status=EvidenceStatus.REJECTED,
        generated_at=datetime.now(timezone.utc), total_oos_trades=40,
    ))
    assert store.is_actionable(rejected_key) is False
    assert store.is_actionable(_key(config_hash="never_registered")) is False


def test_real_campaign_evidence_builder_produces_no_universal_approvals() -> None:
    """Regression guard tied to the real campaign result: no config cleared the gate on both
    BTC/USDT and ETH/USDT, so the evidence builder must never emit UNIVERSAL_APPROVED here."""
    from pathlib import Path

    from packages.evidence.builder import build_evidence_records

    experiments_dir = Path(__file__).resolve().parents[2] / "docs" / "research" / "experiments"
    records = build_evidence_records(experiments_dir, timeframe="1d")
    assert len(records) == 30
    assert all(r.status != EvidenceStatus.UNIVERSAL_APPROVED for r in records)
    approved = [r for r in records if r.status == EvidenceStatus.ASSET_SPECIFIC_APPROVED]
    assert len(approved) == 14
    assert all(r.key.symbol == "BTC/USDT" for r in approved)
