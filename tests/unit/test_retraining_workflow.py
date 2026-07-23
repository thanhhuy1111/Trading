"""Phase 12: retraining workflow smoke test - a small fixture dataset, not an accuracy
campaign. Asserts the workflow runs end-to-end through every stage and always produces a
RESEARCH_ONLY model + an INSUFFICIENT evidence record awaiting human review, never an
automatic promotion."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

import pytest

from packages.domain.enums import RegistryEntryStatus
from packages.evidence.models import EvidenceStatus
from packages.evidence.store import EvidenceStore
from packages.market_data.models import Candle, Timeframe
from packages.registries.registry import ArtifactRegistry, InvalidStatusTransitionError
from packages.retraining.workflow import (
    LABEL_HORIZON_BARS,
    RetrainingWorkflow,
    _triple_barrier_label,
    rollback_model_version,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SYMBOL = "BTC/USDT"


def _oscillating_candles(n: int = 150) -> List[Candle]:
    """Deterministic, non-monotonic series so the model has a genuine (if weak) mix of
    up/down labels to fit and evaluate against - a straight-line series would make every
    label identical and the "accuracy" meaningless even as a smoke test."""
    candles = []
    price = Decimal("50000")
    for i in range(n):
        ct = T0 + timedelta(hours=i)
        # Deterministic pseudo-oscillation: alternates direction every few bars.
        step = Decimal("50") if (i // 3) % 2 == 0 else Decimal("-30")
        price += step
        candles.append(Candle(
            exchange="binance", symbol=SYMBOL, exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + Decimal("20"), low_price=price - Decimal("20"),
            close_price=price, volume=Decimal("10"), is_closed=True,
        ))
    return candles


async def test_retraining_job_runs_all_stages_and_never_auto_promotes() -> None:
    model_registry = ArtifactRegistry("test_retraining_model")
    evidence_store = EvidenceStore()
    workflow = RetrainingWorkflow(model_registry=model_registry, evidence_store=evidence_store)

    result = await workflow.run_training_job(
        candles=_oscillating_candles(150), symbol=SYMBOL, timeframe=Timeframe.H1,
        strategy_name="baseline", strategy_version="1.0.0", strategy_config_hash="hash1",
    )

    expected_stages = [
        "DATASET_SELECTED", "CHECKSUM_COMPUTED", "FEATURES_GENERATED", "LABELS_GENERATED",
        "TIME_SERIES_SPLIT_WITH_PURGE_EMBARGO", "MODEL_TRAINED", "VALIDATED", "CALIBRATED", "TESTED",
        "ARTIFACT_PUBLISHED_RESEARCH_ONLY", "EVIDENCE_REVIEW_REQUESTED",
    ]
    assert result.stages_completed == expected_stages
    assert result.registry_status == RegistryEntryStatus.RESEARCH_ONLY
    assert result.train_sample_count > 0
    assert result.validation_sample_count > 0
    assert result.test_sample_count > 0
    assert 0.0 <= result.test_accuracy <= 1.0

    entry = model_registry.get(f"baseline_{SYMBOL.replace('/', '')}_1h_lr", result.model_version)
    assert entry is not None
    assert entry.status == RegistryEntryStatus.RESEARCH_ONLY

    evidence = evidence_store.lookup(result.evidence_key)
    assert evidence is not None
    assert evidence.status == EvidenceStatus.INSUFFICIENT


async def test_retraining_job_dataset_checksum_is_deterministic() -> None:
    model_registry = ArtifactRegistry("test_retraining_checksum")
    evidence_store = EvidenceStore()
    workflow = RetrainingWorkflow(model_registry=model_registry, evidence_store=evidence_store)
    candles = _oscillating_candles(150)

    result_a = await workflow.run_training_job(
        candles=candles, symbol=SYMBOL, timeframe=Timeframe.H1,
        strategy_name="baseline", strategy_version="1.0.0", strategy_config_hash="hash1",
    )
    result_b = await workflow.run_training_job(
        candles=candles, symbol=SYMBOL, timeframe=Timeframe.H1,
        strategy_name="baseline", strategy_version="1.0.0", strategy_config_hash="hash1",
    )
    assert result_a.dataset_checksum == result_b.dataset_checksum


async def test_retraining_job_rejects_too_small_a_dataset() -> None:
    model_registry = ArtifactRegistry("test_retraining_small")
    evidence_store = EvidenceStore()
    workflow = RetrainingWorkflow(model_registry=model_registry, evidence_store=evidence_store)
    with pytest.raises(ValueError, match="RETRAINING_DATASET_TOO_SMALL"):
        await workflow.run_training_job(
            candles=_oscillating_candles(10), symbol=SYMBOL, timeframe=Timeframe.H1,
            strategy_name="baseline", strategy_version="1.0.0", strategy_config_hash="hash1",
        )


async def test_rollback_disables_a_research_only_model_and_requires_an_actor() -> None:
    model_registry = ArtifactRegistry("test_retraining_rollback")
    evidence_store = EvidenceStore()
    workflow = RetrainingWorkflow(model_registry=model_registry, evidence_store=evidence_store)
    result = await workflow.run_training_job(
        candles=_oscillating_candles(150), symbol=SYMBOL, timeframe=Timeframe.H1,
        strategy_name="baseline", strategy_version="1.0.0", strategy_config_hash="hash1",
    )
    entry_name = f"baseline_{SYMBOL.replace('/', '')}_1h_lr"

    with pytest.raises(ValueError):
        rollback_model_version(model_registry, entry_name, result.model_version, actor="", reason="bad model")

    rolled_back = rollback_model_version(
        model_registry, entry_name, result.model_version, actor="ops_lead_jane", reason="calibration regressed",
    )
    assert rolled_back.status == RegistryEntryStatus.DISABLED

    with pytest.raises(InvalidStatusTransitionError):
        rollback_model_version(model_registry, entry_name, result.model_version, actor="anyone", reason="again")


# --------------------------------------------------------------------------------------
# cost-aware triple-barrier labeling (_triple_barrier_label)
# --------------------------------------------------------------------------------------


def _flat_candles_with_path(entry_price: Decimal, path: List[Decimal], n_before: int = 5) -> List[Candle]:
    """`n_before` flat lead-in candles (so idx has a real "current" bar) followed by one
    candle per `path` price -- close_price drives the barrier walk, high/low give it a
    small +-5 wick so only a deliberate path crosses a barrier."""
    candles = []
    for i in range(n_before):
        ct = T0 + timedelta(hours=i)
        candles.append(Candle(
            exchange="binance", symbol=SYMBOL, exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1,
            open_price=entry_price, high_price=entry_price + Decimal("5"), low_price=entry_price - Decimal("5"),
            close_price=entry_price, volume=Decimal("10"), is_closed=True,
        ))
    for j, price in enumerate(path):
        ct = T0 + timedelta(hours=n_before + j)
        candles.append(Candle(
            exchange="binance", symbol=SYMBOL, exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1,
            open_price=price, high_price=price + Decimal("5"), low_price=price - Decimal("5"),
            close_price=price, volume=Decimal("10"), is_closed=True,
        ))
    return candles


def test_triple_barrier_label_is_one_for_a_genuine_net_profitable_upper_touch():
    entry = Decimal("50000")
    # +3% on bar 1 of the horizon -- clears the 1.5% upper barrier net of realistic costs.
    path = [entry * Decimal("1.03")] + [entry * Decimal("1.03")] * (LABEL_HORIZON_BARS - 1)
    candles = _flat_candles_with_path(entry, path)
    idx = 4  # the last flat lead-in candle, i.e. "now"
    label = _triple_barrier_label(candles, idx, SYMBOL)
    assert label == 1


def test_triple_barrier_label_is_zero_for_a_lower_barrier_touch():
    entry = Decimal("50000")
    path = [entry * Decimal("0.97")] * LABEL_HORIZON_BARS
    candles = _flat_candles_with_path(entry, path)
    label = _triple_barrier_label(candles, 4, SYMBOL)
    assert label == 0


def test_triple_barrier_label_is_zero_for_a_timeout_with_no_barrier_touch():
    entry = Decimal("50000")
    # Drifts up by well under 1.5% over the whole horizon -- never touches either barrier.
    path = [entry + Decimal("10") * (j + 1) for j in range(LABEL_HORIZON_BARS)]
    candles = _flat_candles_with_path(entry, path)
    label = _triple_barrier_label(candles, 4, SYMBOL)
    assert label == 0


def test_triple_barrier_label_is_none_without_enough_forward_history():
    entry = Decimal("50000")
    path = [entry * Decimal("1.03")] * (LABEL_HORIZON_BARS - 1)  # one bar short of the horizon
    candles = _flat_candles_with_path(entry, path)
    label = _triple_barrier_label(candles, 4, SYMBOL)
    assert label is None
