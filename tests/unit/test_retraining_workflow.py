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
from packages.retraining.workflow import RetrainingWorkflow, rollback_model_version

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
