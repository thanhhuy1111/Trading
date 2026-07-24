import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from packages.common.immutable import FrozenMapping
from packages.experiments.service import (
    CanonicalPayload,
    ExperimentOutcomeEvent,
    ExperimentRecord,
    ExperimentStore,
)


def _record(
    *,
    sequence: int = 1,
    analysis_id: str = "analysis-1",
    disagreement: bool | None = False,
    rejected: bool = False,
) -> ExperimentRecord:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=sequence)
    raw = CanonicalPayload.capture({"close": "50000", "source": "binance_public"})
    normalized = CanonicalPayload.capture({"close": "50000"})
    features = CanonicalPayload.capture({"rsi_14": "55"})
    evidence = CanonicalPayload.capture({"evidence_ids": ["ev-1"]})
    models = FrozenMapping({"quantitative": "xgb-approved-v1"})
    prompts = FrozenMapping({"technical": "technical-v1"})
    experiment_id = ExperimentRecord.derive_id(
        analysis_id=analysis_id,
        symbol="BTCUSDT",
        timeframe="4h",
        as_of_time=as_of,
        raw_checksum=raw.checksum,
        normalized_checksum=normalized.checksum,
        feature_checksum=features.checksum,
        evidence_checksum=evidence.checksum,
        model_versions=dict(models),
        prompt_versions=dict(prompts),
    )
    return ExperimentRecord(
        experiment_id=experiment_id,
        analysis_id=analysis_id,
        sequence_number=sequence,
        symbol="BTCUSDT",
        timeframe="4h",
        as_of_time=as_of,
        recorded_at=as_of + timedelta(seconds=1),
        raw_inputs=raw,
        normalized_inputs=normalized,
        feature_snapshot=features,
        evidence_snapshot=evidence,
        model_versions=models,
        prompt_versions=prompts,
        agent_outputs=CanonicalPayload.capture({"technical": "AVAILABLE"}),
        debate_transcript=CanonicalPayload.capture({"status": "COMPLETE"}),
        verification_result=CanonicalPayload.capture({"accepted": not rejected}),
        risk_result=CanonicalPayload.capture({"approved": not rejected}),
        manager_result=CanonicalPayload.capture({"action": "LONG" if not rejected else "NO_DECISION"}),
        agent_disagreement=disagreement,
        verification_rejected=rejected,
        input_tokens=100,
        output_tokens=20,
        cost_amount=Decimal("0.01"),
        cost_currency="USD",
        latency_ms=100.0 * sequence,
        retry_count=0,
        expected_field_count=10,
        missing_field_count=sequence - 1,
        data_quality=CanonicalPayload.capture({"status": "HEALTHY"}),
    )


def _outcome(
    record: ExperimentRecord,
    *,
    sequence: int,
    correct: bool | None,
    pnl: Decimal | None,
    simulated_return: Decimal | None,
    drawdown: Decimal | None,
) -> ExperimentOutcomeEvent:
    available = record.as_of_time + timedelta(hours=4)
    payload = CanonicalPayload.capture({"label": "BULLISH", "horizon_close": "51000"})
    event_id = ExperimentOutcomeEvent.derive_id(
        record.experiment_id,
        "4h",
        available,
        payload.checksum,
    )
    return ExperimentOutcomeEvent(
        event_id=event_id,
        experiment_id=record.experiment_id,
        sequence_number=sequence,
        horizon="4h",
        outcome_available_at=available,
        observed_at=available + timedelta(seconds=1),
        actual_market_outcome=payload,
        prediction_correct=correct,
        simulated_pnl=pnl,
        pnl_currency="USDT" if pnl is not None else None,
        simulated_return=simulated_return,
        drawdown_pct=drawdown,
    )


def test_reproducible_id_append_only_and_conflict_detection() -> None:
    first = _record()
    replay = _record()
    assert first.experiment_id == replay.experiment_id
    offset_payload = first.model_dump()
    offset = timezone(timedelta(hours=7))
    offset_payload["as_of_time"] = first.as_of_time.astimezone(offset)
    offset_payload["recorded_at"] = first.recorded_at.astimezone(offset)
    assert ExperimentRecord.model_validate(offset_payload).experiment_id == first.experiment_id
    store = ExperimentStore()
    assert store.append(first) == first
    assert store.append(replay) == first

    conflict = first.model_copy(update={"latency_ms": 999.0})
    with pytest.raises(ValueError, match="EXPERIMENT_APPEND_CONFLICT"):
        store.append(conflict)
    with pytest.raises(ValueError, match="EXPERIMENT_SEQUENCE_CONFLICT"):
        store.append(_record(sequence=1, analysis_id="different-analysis"))


def test_secret_material_is_rejected_before_capture() -> None:
    with pytest.raises(ValueError, match="EXPERIMENT_SECRET_MATERIAL_REJECTED"):
        CanonicalPayload.capture({"api_key": "secret-value"})
    with pytest.raises(ValueError, match="EXPERIMENT_SECRET_MATERIAL_REJECTED"):
        CanonicalPayload.capture({"database": "postgresql://user:password@localhost/db"})
    with pytest.raises(ValueError, match="EXPERIMENT_SECRET_MATERIAL_REJECTED"):
        CanonicalPayload.capture({"note": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"})
    with pytest.raises(ValueError, match="EXPERIMENT_SECRET_MATERIAL_REJECTED"):
        CanonicalPayload.capture({"transcript": "sk-proj-abcdefghijklmnopqrstuv"})
    with pytest.raises(ValueError, match="EXPERIMENT_SECRET_MATERIAL_REJECTED"):
        CanonicalPayload(
            canonical_json='{"api_key":"secret-value"}',
            checksum="0" * 64,
        )
    with pytest.raises(ValueError, match="EXPERIMENT_UNSUPPORTED_JSON_TYPE"):
        CanonicalPayload.capture({"unordered": {"a", "b"}})
    valid = _record()
    bypass = valid.raw_inputs.model_copy(
        update={
            "canonical_json": '{"api_key":"secret-value"}',
            "checksum": "0" * 64,
        }
    )
    with pytest.raises(ValueError, match="EXPERIMENT_SECRET_MATERIAL_REJECTED"):
        ExperimentStore().append(valid.model_copy(update={"raw_inputs": bypass}))


def test_deterministic_export_never_overwrites(tmp_path) -> None:
    store = ExperimentStore()
    store.append(_record())
    store.append(_record(sequence=2, analysis_id="analysis-2"))
    destination = tmp_path / "experiments.jsonl"

    checksum = store.export_jsonl(destination)
    rows = [json.loads(line) for line in destination.read_text().splitlines()]

    assert len(checksum) == 64
    assert rows[0]["record_type"] == "MANIFEST"
    assert [row["payload"]["sequence_number"] for row in rows[1:]] == [1, 2]
    with pytest.raises(FileExistsError, match="EXPERIMENT_EXPORT_EXISTS"):
        store.export_jsonl(destination)

    other = ExperimentStore()
    other.append(_record())
    raced = tmp_path / "raced.jsonl"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(current.export_jsonl, raced)
            for current in (store, other)
        ]
    assert sum(future.exception() is None for future in futures) == 1
    assert sum(isinstance(future.exception(), FileExistsError) for future in futures) == 1


def test_report_uses_only_observed_values() -> None:
    store = ExperimentStore()
    first = store.append(_record(sequence=1, rejected=False))
    second = store.append(
        _record(sequence=2, analysis_id="analysis-2", disagreement=True, rejected=True)
    )
    store.append(_record(sequence=3, analysis_id="analysis-3", disagreement=None))
    store.append_outcome(
        _outcome(
            first,
            sequence=1,
            correct=True,
            pnl=Decimal("10"),
            simulated_return=Decimal("0.01"),
            drawdown=Decimal("0.02"),
        )
    )
    store.append_outcome(
        _outcome(
            second,
            sequence=2,
            correct=False,
            pnl=Decimal("-4"),
            simulated_return=Decimal("-0.004"),
            drawdown=Decimal("0.03"),
        )
    )

    report = store.report("4h")

    assert report.experiment_count == 3
    assert report.prediction_accuracy == Decimal("0.5")
    assert report.total_simulated_pnl == Decimal("6")
    assert report.pnl_currency == "USDT"
    assert report.simulated_win_rate == Decimal("0.5")
    assert report.maximum_observed_drawdown_pct == Decimal("0.03")
    assert report.simulated_return_observation_count == 2
    assert report.drawdown_observation_count == 2
    assert report.agent_disagreement_rate == Decimal("0.5")
    assert report.verification_rejection_rate == Decimal(1) / Decimal(3)
    assert report.average_cost_per_analysis == Decimal("0.01")
    assert report.latency_p50_ms == 200.0
    assert report.latency_p95_ms == 300.0
    assert report.missing_data_rate == Decimal(3) / Decimal(30)
    assert report.evaluated_prediction_count == 2
    assert report.cost_observation_count == 3
    assert report.latency_observation_count == 3


def test_outcomes_are_temporal_append_only_and_retention_is_explicit() -> None:
    store = ExperimentStore()
    record = store.append(_record())
    outcome = _outcome(
        record,
        sequence=1,
        correct=True,
        pnl=Decimal("1"),
        simulated_return=Decimal("0.001"),
        drawdown=Decimal("0"),
    )
    assert store.append_outcome(outcome) == outcome
    assert store.append_outcome(outcome) == outcome

    early_payload = CanonicalPayload.capture({"label": "EARLY"})
    early = ExperimentOutcomeEvent(
        event_id=ExperimentOutcomeEvent.derive_id(
            record.experiment_id,
            "4h",
            record.as_of_time,
            early_payload.checksum,
        ),
        experiment_id=record.experiment_id,
        sequence_number=2,
        horizon="4h",
        outcome_available_at=record.as_of_time,
        observed_at=record.as_of_time + timedelta(hours=4),
        actual_market_outcome=early_payload,
    )
    with pytest.raises(ValueError, match="EXPERIMENT_OUTCOME_LOOKAHEAD"):
        store.append_outcome(early)
    candidates = store.retention_candidates(
        record.recorded_at + timedelta(days=366)
    )
    assert candidates.experiment_ids == (record.experiment_id,)
    assert candidates.outcome_event_ids == (outcome.event_id,)
    assert candidates.archive_before_delete is True

    assert ExperimentOutcomeEvent.derive_id(
        record.experiment_id,
        "60m",
        outcome.outcome_available_at,
        outcome.actual_market_outcome.checksum,
    ) == ExperimentOutcomeEvent.derive_id(
        record.experiment_id,
        "1h",
        outcome.outcome_available_at,
        outcome.actual_market_outcome.checksum,
    )
