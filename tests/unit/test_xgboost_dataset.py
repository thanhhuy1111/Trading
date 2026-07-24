"""Offline acceptance tests for the Phase 4B point-in-time XGBoost dataset."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

import pytest
from pydantic import ValidationError

from packages.features.models import FeatureQualityStatus
from packages.market_data.derivatives_models import (
    DerivativesMetricLineage,
    DerivativesSnapshot,
)
from packages.market_data.models import Candle, DataQualityStatus, Timeframe
from packages.retraining.xgboost_contracts import (
    DatasetBuildStatus,
    DatasetMode,
    TargetClass,
)
from packages.retraining.xgboost_dataset import (
    DERIVATIVES_FEATURE_NAMES,
    PRICE_FEATURE_NAMES,
    classify_target,
    xgboost_dataset_builder,
)

BASE_TIME = datetime(2025, 1, 1, tzinfo=timezone.utc)
H4 = timedelta(hours=4)


def _candles(
    count: int = 70,
    *,
    received_offset: timedelta = timedelta(minutes=1),
    exchange: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: Timeframe = Timeframe.H4,
) -> list[Candle]:
    candles: list[Candle] = []
    previous_close = Decimal("50000")
    for index in range(count):
        open_time = BASE_TIME + index * H4
        drift = Decimal(index * 17)
        oscillation = Decimal((index % 7) - 3) * Decimal("41")
        close = Decimal("50000") + drift + oscillation
        open_price = previous_close
        high = max(open_price, close) + Decimal("120") + Decimal(index % 5)
        low = min(open_price, close) - Decimal("110") - Decimal(index % 3)
        close_time = open_time + H4 - timedelta(milliseconds=1)
        candles.append(
            Candle(
                exchange=exchange,
                symbol=symbol,
                exchange_timestamp=close_time,
                received_timestamp=close_time + received_offset,
                source="offline_fixture",
                data_quality_status=DataQualityStatus.HEALTHY,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open_price=open_price,
                high_price=high,
                low_price=low,
                close_price=close,
                volume=Decimal("1000") + Decimal(index * 13 + index % 4),
                quote_volume=close * Decimal("1000"),
                trades_count=100 + index,
                is_closed=True,
            )
        )
        previous_close = close
    return candles


def _derivatives(
    as_of_time: datetime,
    *,
    count: int = 20,
    exchange: str = "binance_usdm_futures",
    symbol: str = "BTC/USDT",
    availability_delay: timedelta = timedelta(seconds=30),
    received_offset: timedelta = timedelta(seconds=20),
    irregular_index: int | None = None,
    with_lineage: bool = True,
    status: DataQualityStatus = DataQualityStatus.HEALTHY,
) -> list[DerivativesSnapshot]:
    snapshots: list[DerivativesSnapshot] = []
    first_event = as_of_time - timedelta(minutes=5 * count)
    for index in range(count):
        event_time = first_event + timedelta(minutes=5 * index)
        if irregular_index is not None and index >= irregular_index:
            event_time += timedelta(minutes=2)
        available_at = event_time + availability_delay
        lineage = (
            {
                metric: DerivativesMetricLineage(
                    event_time=event_time,
                    available_at=available_at,
                    source_timestamps={f"{metric}_endpoint": event_time},
                )
                for metric in ("funding_rate", "open_interest")
            }
            if with_lineage
            else {}
        )
        snapshots.append(
            DerivativesSnapshot(
                exchange=exchange,
                symbol=symbol,
                exchange_timestamp=event_time,
                received_timestamp=event_time + received_offset,
                source="offline_fixture",
                data_quality_status=status,
                funding_rate=Decimal("0.0001") + Decimal(index) / Decimal("1000000"),
                open_interest=Decimal("10000") + Decimal(index * 25),
                futures_basis_bps=Decimal("12"),
                metric_lineage=lineage,
            )
        )
    return snapshots


def _build_price(candles: Sequence[Candle]):
    return xgboost_dataset_builder.build(
        candles,
        mode=DatasetMode.PRICE_ONLY,
        threshold_k=Decimal("0.5"),
    )


def _build_plus(
    candles: Sequence[Candle],
    derivatives: Sequence[DerivativesSnapshot],
):
    return xgboost_dataset_builder.build(
        candles,
        mode=DatasetMode.PRICE_PLUS_DERIVATIVES,
        threshold_k=Decimal("0.5"),
        derivatives_snapshots=derivatives,
    )


def test_price_only_dataset_is_deterministic_versioned_and_temporally_safe() -> None:
    first = _build_price(_candles(received_offset=timedelta(minutes=1)))
    reloaded = _build_price(_candles(received_offset=timedelta(days=3)))

    assert first.status == DatasetBuildStatus.VALID
    assert first.samples
    assert first.report.dataset_checksum == reloaded.report.dataset_checksum
    assert [sample.sample_id for sample in first.samples] == [
        sample.sample_id for sample in reloaded.samples
    ]
    assert first.report.feature_schema_hash
    assert first.report.dataset_version == "xgb_direction_dataset_v1"
    assert sum(first.report.class_distribution.counts.values()) == len(first.samples)
    assert sum(first.report.class_distribution.shares.values()) == pytest.approx(1.0)
    for sample in first.samples:
        assert sample.feature_names == PRICE_FEATURE_NAMES
        assert sample.feature_available_at <= sample.as_of_time < sample.target_time
        assert not {
            "future_close",
            "future_return",
            "target_class",
            "target_time",
        }.intersection(sample.feature_values)
        assert sample.ingestion_audit["price_received_at"] > sample.as_of_time


def test_modes_are_separate_and_plus_mode_never_falls_back() -> None:
    candles = _candles(30)
    price = _build_price(candles)
    missing = _build_plus(candles, [])
    plus = _build_plus(candles, _derivatives(price.samples[-1].as_of_time))

    assert price.status == DatasetBuildStatus.VALID
    assert missing.status == DatasetBuildStatus.REJECTED
    assert "DERIVATIVES_HISTORY_MISSING" in missing.reason_codes
    assert plus.status == DatasetBuildStatus.VALID
    assert plus.samples[0].feature_names == PRICE_FEATURE_NAMES + DERIVATIVES_FEATURE_NAMES
    assert "futures_basis_momentum_6" not in plus.samples[0].feature_values
    assert plus.samples[0].feature_lineage.derivatives is not None
    assert plus.samples[0].feature_lineage.derivatives.source_exchange == (
        "binance_usdm_futures"
    )
    with pytest.raises(TypeError):
        plus.samples[0].feature_values["future_return"] = Decimal("99")
    with pytest.raises(TypeError):
        dict.__setitem__(
            plus.samples[0].feature_values,
            "future_return",
            Decimal("99"),
        )


@pytest.mark.parametrize(
    ("exchange_symbol", "timeframe", "candles", "reason"),
    [
        ("ETHUSDT", Timeframe.H4, _candles(), "UNSUPPORTED_SYMBOL"),
        ("BTC/USDT", Timeframe.H4, _candles(), "UNSUPPORTED_SYMBOL"),
        ("BTCUSDT", Timeframe.H1, _candles(), "UNSUPPORTED_TIMEFRAME"),
        (
            "BTCUSDT",
            Timeframe.H4,
            _candles(exchange="binance_usdm_futures"),
            "CANDLE_SOURCE_MISMATCH",
        ),
        (
            "BTCUSDT",
            Timeframe.H4,
            _candles(symbol="ETH/USDT"),
            "CANDLE_SOURCE_MISMATCH",
        ),
    ],
)
def test_exact_registered_mapping_and_source_are_enforced(
    exchange_symbol: str,
    timeframe: Timeframe,
    candles: Sequence[Candle],
    reason: str,
) -> None:
    result = xgboost_dataset_builder.build(
        candles,
        mode=DatasetMode.PRICE_ONLY,
        threshold_k=Decimal("0.5"),
        exchange_symbol=exchange_symbol,
        timeframe=timeframe,
    )
    assert result.status == DatasetBuildStatus.REJECTED
    assert result.reason_codes == (reason,)


def test_derivatives_wrong_venue_and_legacy_lineage_fail_closed() -> None:
    candles = _candles(30)
    as_of_time = _build_price(candles).samples[-1].as_of_time

    wrong_venue = _build_plus(
        candles,
        _derivatives(as_of_time, exchange="binance"),
    )
    legacy = _build_plus(
        candles,
        _derivatives(as_of_time, with_lineage=False),
    )
    wrong_symbol = _build_plus(
        candles,
        _derivatives(as_of_time, symbol="ETH/USDT"),
    )

    assert "DERIVATIVES_SOURCE_MISMATCH" in wrong_venue.reason_codes
    assert "DERIVATIVES_LINEAGE_MISSING" in legacy.reason_codes
    assert "DERIVATIVES_SOURCE_MISMATCH" in wrong_symbol.reason_codes


def test_delayed_availability_unhealthy_source_and_irregular_cadence_are_rejected() -> None:
    candles = _candles(30)
    as_of_time = _build_price(candles).samples[-1].as_of_time

    delayed = _build_plus(
        candles,
        _derivatives(as_of_time, availability_delay=timedelta(minutes=10)),
    )
    unhealthy = _build_plus(
        candles,
        _derivatives(as_of_time, status=DataQualityStatus.DEGRADED),
    )
    irregular = _build_plus(
        candles,
        _derivatives(as_of_time, irregular_index=10),
    )

    assert "DERIVATIVES_FUTURE_AVAILABILITY" in delayed.reason_codes
    assert "DERIVATIVES_SOURCE_UNHEALTHY" in unhealthy.reason_codes
    assert "DERIVATIVES_CADENCE_INVALID" in irregular.reason_codes


def test_short_stale_and_inconsistent_derivatives_lineage_are_rejected() -> None:
    candles = _candles(30)
    as_of_time = _build_price(candles).samples[-1].as_of_time
    short = _build_plus(candles, _derivatives(as_of_time, count=19))
    stale = _build_plus(
        candles,
        _derivatives(as_of_time - timedelta(minutes=10)),
    )
    inconsistent_history = _derivatives(
        as_of_time,
        received_offset=timedelta(minutes=2),
    )
    inconsistent = _build_plus(candles, inconsistent_history)

    assert "DERIVATIVES_HISTORY_MISSING" in short.reason_codes
    assert "DERIVATIVES_SNAPSHOT_STALE" in stale.reason_codes
    assert "DERIVATIVES_LINEAGE_INVALID" in inconsistent.reason_codes


def test_mixed_metric_source_timestamps_use_latest_availability() -> None:
    candles = _candles(30)
    as_of_time = _build_price(candles).samples[-1].as_of_time
    history = _derivatives(as_of_time)
    delayed_open_interest: list[DerivativesSnapshot] = []
    for snapshot in history:
        funding = snapshot.metric_lineage["funding_rate"]
        delayed_source_time = as_of_time + timedelta(seconds=1)
        delayed_open_interest.append(
            snapshot.model_copy(
                update={
                    "metric_lineage": {
                        "funding_rate": funding,
                        "open_interest": DerivativesMetricLineage(
                            event_time=snapshot.metric_lineage[
                                "open_interest"
                            ].event_time,
                            available_at=delayed_source_time,
                            source_timestamps={
                                "open_interest_endpoint": delayed_source_time,
                            },
                        ),
                    },
                }
            )
        )

    result = _build_plus(candles, delayed_open_interest)
    assert "DERIVATIVES_FUTURE_AVAILABILITY" in result.reason_codes

    with pytest.raises(ValidationError, match="source timestamp cannot be after"):
        DerivativesMetricLineage(
            event_time=as_of_time - timedelta(minutes=5),
            available_at=as_of_time - timedelta(minutes=1),
            source_timestamps={"late_source": as_of_time},
        )


def test_valid_mixed_contributing_source_timestamps_are_preserved() -> None:
    candles = _candles(30)
    as_of_time = _build_price(candles).samples[-1].as_of_time
    history = _derivatives(as_of_time)
    mixed: list[DerivativesSnapshot] = []
    for snapshot in history:
        lineage = {}
        for metric, metric_lineage in snapshot.metric_lineage.items():
            lineage[metric] = DerivativesMetricLineage(
                event_time=metric_lineage.event_time,
                available_at=metric_lineage.available_at,
                source_timestamps={
                    "source_a": metric_lineage.event_time,
                    "source_b": metric_lineage.event_time + timedelta(seconds=20),
                },
            )
        mixed.append(snapshot.model_copy(update={"metric_lineage": lineage}))

    result = _build_plus(candles, mixed)
    assert result.status == DatasetBuildStatus.VALID
    nested = result.samples[0].feature_lineage.derivatives
    assert nested is not None
    assert len(nested.metric_lineage["funding_rate"][0].source_timestamps) == 2


def test_metric_lineage_not_snapshot_timestamp_controls_derivatives_order() -> None:
    candles = _candles(30)
    as_of_time = _build_price(candles).samples[-1].as_of_time
    history = _derivatives(as_of_time)
    reversed_snapshot_times = [
        snapshot.model_copy(
            update={"exchange_timestamp": history[-index - 1].exchange_timestamp}
        )
        for index, snapshot in enumerate(history)
    ]

    canonical = _build_plus(candles, history)
    crossed = _build_plus(candles, reversed_snapshot_times)
    assert canonical.status == crossed.status == DatasetBuildStatus.VALID
    assert canonical.samples[0].feature_values == crossed.samples[0].feature_values


def test_append_future_inputs_does_not_change_historical_samples() -> None:
    original_candles = _candles(65)
    extended_candles = _candles(72)
    original = _build_price(original_candles)
    extended = _build_price(extended_candles)
    extended_by_id = {sample.sample_id: sample for sample in extended.samples}

    assert original.samples
    for sample in original.samples:
        assert sample.sample_id in extended_by_id
        assert sample.model_dump(exclude={"ingestion_audit"}) == extended_by_id[
            sample.sample_id
        ].model_dump(exclude={"ingestion_audit"})


def test_append_future_derivatives_snapshot_does_not_change_historical_sample() -> None:
    candles = _candles(30)
    as_of_time = _build_price(candles).samples[-1].as_of_time
    history = _derivatives(as_of_time)
    original = _build_plus(candles, history)
    future_window_as_of = as_of_time + timedelta(minutes=10)
    future = _derivatives(future_window_as_of, count=1)[0]
    extended = _build_plus(candles, [*history, future])

    assert original.status == DatasetBuildStatus.VALID
    assert extended.status == DatasetBuildStatus.VALID
    assert original.samples[0].model_dump(exclude={"ingestion_audit"}) == extended.samples[
        0
    ].model_dump(exclude={"ingestion_audit"})


def test_plus_checksum_ignores_price_and_derivatives_ingestion_clock() -> None:
    first_candles = _candles(30, received_offset=timedelta(minutes=1))
    second_candles = _candles(30, received_offset=timedelta(days=2))
    as_of_time = _build_price(first_candles).samples[-1].as_of_time
    first_history = _derivatives(
        as_of_time,
        received_offset=timedelta(seconds=20),
    )
    second_history = _derivatives(
        as_of_time,
        received_offset=timedelta(seconds=25),
    )

    first = _build_plus(first_candles, first_history)
    second = _build_plus(second_candles, second_history)
    assert first.status == second.status == DatasetBuildStatus.VALID
    assert first.report.dataset_checksum == second.report.dataset_checksum


def test_price_gap_resets_history_and_target_gap_is_reported() -> None:
    candles = _candles(70)
    with_gap = [*candles[:35], *candles[36:]]
    result = _build_price(with_gap)

    assert result.status == DatasetBuildStatus.VALID
    assert result.report.rejection_counts["TARGET_GAP"] >= 1
    assert result.report.rejection_counts["INSUFFICIENT_PRICE_HISTORY"] >= 1


def test_duplicate_and_out_of_order_candles_are_rejected() -> None:
    candles = _candles(40)
    duplicate = _build_price([*candles[:20], candles[19], *candles[20:]])
    out_of_order = _build_price([*candles[:20], candles[21], candles[20], *candles[22:]])

    assert duplicate.reason_codes == ("CANDLE_ORDER_INVALID",)
    assert out_of_order.reason_codes == ("CANDLE_ORDER_INVALID",)


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        (
            {"close_time": BASE_TIME + timedelta(hours=1) - timedelta(milliseconds=1)},
            "CANDLE_INTERVAL_INVALID",
        ),
        (
            {"exchange_timestamp": BASE_TIME + timedelta(hours=3)},
            "CANDLE_EVENT_TIME_MISMATCH",
        ),
        (
            {"data_quality_status": DataQualityStatus.UNHEALTHY},
            "CANDLE_SOURCE_UNHEALTHY",
        ),
    ],
)
def test_malformed_or_unhealthy_candles_are_rejected(
    update: dict[str, object],
    reason: str,
) -> None:
    candles = _candles(40)
    malformed = candles[0].model_copy(update=update)
    result = _build_price([malformed, *candles[1:]])
    assert result.reason_codes == (reason,)


def test_label_boundaries_and_invalid_threshold() -> None:
    bullish, threshold = classify_target(
        Decimal("0.021"),
        Decimal("0.01"),
        Decimal("2"),
    )
    bearish, _ = classify_target(
        Decimal("-0.021"),
        Decimal("0.01"),
        Decimal("2"),
    )
    positive_boundary, _ = classify_target(
        Decimal("0.02"),
        Decimal("0.01"),
        Decimal("2"),
    )
    negative_boundary, _ = classify_target(
        Decimal("-0.02"),
        Decimal("0.01"),
        Decimal("2"),
    )

    assert threshold == Decimal("0.02")
    assert bullish == TargetClass.BULLISH
    assert bearish == TargetClass.BEARISH
    assert positive_boundary == TargetClass.NEUTRAL
    assert negative_boundary == TargetClass.NEUTRAL
    invalid = xgboost_dataset_builder.build(
        _candles(),
        mode=DatasetMode.PRICE_ONLY,
        threshold_k=Decimal("0"),
    )
    assert invalid.reason_codes == ("INVALID_THRESHOLD_K",)
    assert invalid.report.label_threshold_k == Decimal("0")
    assert invalid.report.candidate_count == 0
    assert invalid.report.rejected_count == 0
    assert invalid.report.rejection_counts == {}
    assert invalid.report.request_rejection_codes == ("INVALID_THRESHOLD_K",)


def test_direct_contract_rejects_future_lineage_schema_label_and_report_tampering() -> None:
    result = _build_price(_candles(30))
    sample = result.samples[0]
    future_price = sample.feature_lineage.price.model_copy(
        update={"source_available_at": sample.as_of_time + timedelta(seconds=1)}
    )
    future_lineage = sample.feature_lineage.model_copy(update={"price": future_price})

    with pytest.raises(ValidationError, match="price lineage"):
        sample.__class__(
            **{
                **sample.model_dump(),
                "feature_lineage": future_lineage,
            }
        )
    with pytest.raises(ValidationError, match="dataset mode schema"):
        sample.__class__(
            **{
                **sample.model_dump(),
                "feature_names": ("made_up_signal",),
                "feature_values": {"made_up_signal": Decimal("1")},
            }
        )
    with pytest.raises(ValidationError, match="future_return"):
        sample.__class__(
            **{
                **sample.model_dump(),
                "future_return": sample.future_return + Decimal("0.1"),
            }
        )
    with pytest.raises(ValidationError, match="feature_status"):
        sample.__class__(
            **{
                **sample.model_dump(),
                "feature_status": FeatureQualityStatus.INVALID,
            }
        )

    mismatched_price = sample.feature_lineage.price.model_copy(
        update={"source_exchange": "coinbase", "source_symbol": "ETH/USD"}
    )
    mismatched_lineage = sample.feature_lineage.model_copy(
        update={"price": mismatched_price}
    )
    with pytest.raises(ValidationError, match="price lineage source"):
        sample.__class__(
            **{
                **sample.model_dump(),
                "feature_lineage": mismatched_lineage,
            }
        )
    wrong_versions = sample.feature_lineage.price.model_copy(
        update={
            "calculator_versions": {
                name: "2.0.0" for name in PRICE_FEATURE_NAMES
            }
        }
    )
    wrong_version_lineage = sample.feature_lineage.model_copy(
        update={"price": wrong_versions}
    )
    with pytest.raises(ValidationError, match="calculator schema"):
        sample.__class__(
            **{
                **sample.model_dump(),
                "feature_lineage": wrong_version_lineage,
            }
        )

    tampered_report = result.report.model_copy(
        update={"dataset_checksum": "0" * 64}
    )
    with pytest.raises(ValidationError, match="checksum"):
        result.__class__(
            status=result.status,
            dataset_mode=result.dataset_mode,
            samples=result.samples,
            report=tampered_report,
            reason_codes=result.reason_codes,
        )

    bad_range = result.report.model_copy(update={"start_time": None, "end_time": None})
    with pytest.raises(ValidationError, match="time range"):
        result.__class__(
            status=result.status,
            dataset_mode=result.dataset_mode,
            samples=result.samples,
            report=bad_range,
        )

    tampered_sample = sample.model_copy(update={"sample_id": "0" * 64})
    with pytest.raises(ValidationError, match="sample_id"):
        result.__class__(
            status=result.status,
            dataset_mode=result.dataset_mode,
            samples=(tampered_sample, *result.samples[1:]),
            report=result.report,
        )

    candidate_distributions = dict(result.report.candidate_class_distributions)
    candidate_distributions["0.25"] = candidate_distributions["0.25"].model_copy(
        update={
            "shares": {
                TargetClass.BEARISH.value: 99.0,
                TargetClass.NEUTRAL.value: 0.0,
                TargetClass.BULLISH.value: 0.0,
            }
        }
    )
    bad_shares = result.report.model_copy(
        update={"candidate_class_distributions": candidate_distributions}
    )
    with pytest.raises(ValidationError, match="distribution shares"):
        result.__class__(
            status=result.status,
            dataset_mode=result.dataset_mode,
            samples=result.samples,
            report=bad_shares,
        )

    plus_candles = _candles(30)
    plus_as_of = _build_price(plus_candles).samples[-1].as_of_time
    plus_sample = _build_plus(
        plus_candles,
        _derivatives(plus_as_of),
    ).samples[0]
    with pytest.raises(ValidationError, match="lineage is stale"):
        plus_sample.__class__(
            **{
                **plus_sample.model_dump(),
                "as_of_time": plus_sample.as_of_time + timedelta(minutes=6),
            }
        )

    derivatives_lineage = plus_sample.feature_lineage.derivatives
    assert derivatives_lineage is not None
    stale_open_interest = tuple(
        DerivativesMetricLineage(
            event_time=lineage.event_time - timedelta(hours=1),
            available_at=lineage.available_at - timedelta(hours=1),
            source_timestamps={
                source: timestamp - timedelta(hours=1)
                for source, timestamp in lineage.source_timestamps.items()
            },
        )
        for lineage in derivatives_lineage.metric_lineage["open_interest"]
    )
    mixed_histories = dict(derivatives_lineage.metric_lineage)
    mixed_histories["open_interest"] = stale_open_interest
    all_events = [
        lineage.event_time
        for history in mixed_histories.values()
        for lineage in history
    ]
    mixed_derivatives = derivatives_lineage.model_copy(
        update={
            "metric_lineage": mixed_histories,
            "oldest_sample_timestamp": min(all_events),
            "newest_sample_timestamp": max(all_events),
        }
    )
    mixed_feature_lineage = plus_sample.feature_lineage.model_copy(
        update={"derivatives": mixed_derivatives}
    )
    with pytest.raises(ValidationError, match="required derivatives metric is stale"):
        plus_sample.__class__(
            **{
                **plus_sample.model_dump(),
                "feature_lineage": mixed_feature_lineage,
            }
        )
