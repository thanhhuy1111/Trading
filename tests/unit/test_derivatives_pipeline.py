"""Offline tests for DerivativesFeaturePipeline.compute() -- anti-lookahead-leakage filtering
and the WARMING_UP-vs-DEGRADED-vs-VALID quality status logic."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

from packages.features.derivatives_models import DerivativesFeatureComputationRequest
from packages.features.derivatives_pipeline import derivatives_feature_pipeline
from packages.features.models import FeatureQualityStatus
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.models import DataQualityStatus

SYMBOL = "BTC/USDT"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _snapshot(
    ts: datetime,
    funding_rate: str = "0.0001",
    open_interest: str = "1000",
    futures_basis_bps: str = "10",
) -> DerivativesSnapshot:
    return DerivativesSnapshot(
        exchange="binance_usdm_futures",
        symbol=SYMBOL,
        exchange_timestamp=ts,
        data_quality_status=DataQualityStatus.HEALTHY,
        funding_rate=Decimal(funding_rate),
        open_interest=Decimal(open_interest),
        futures_basis_bps=Decimal(futures_basis_bps),
    )


def _rich_history(n: int, start: datetime = BASE_TIME) -> List[DerivativesSnapshot]:
    return [_snapshot(start + timedelta(minutes=5 * i)) for i in range(n)]


def test_compute_filters_out_snapshots_after_as_of_time() -> None:
    as_of = BASE_TIME + timedelta(minutes=5 * 25)
    history = _rich_history(25, start=BASE_TIME)

    request = DerivativesFeatureComputationRequest(
        exchange="binance_usdm_futures", symbol=SYMBOL, feature_set="derivatives_v1", as_of_time=as_of,
    )
    baseline = derivatives_feature_pipeline.compute(request, history)

    future_snapshot = _snapshot(as_of + timedelta(minutes=5), funding_rate="9.9999")
    with_future = derivatives_feature_pipeline.compute(request, history + [future_snapshot])

    assert with_future.values == baseline.values
    assert with_future.lineage.newest_sample_timestamp == baseline.lineage.newest_sample_timestamp
    assert with_future.lineage.sample_count == baseline.lineage.sample_count


def test_compute_reports_warming_up_when_history_is_short() -> None:
    as_of = BASE_TIME + timedelta(minutes=5 * 3)
    history = _rich_history(3, start=BASE_TIME)  # well short of every calculator's lookback

    request = DerivativesFeatureComputationRequest(
        exchange="binance_usdm_futures", symbol=SYMBOL, feature_set="derivatives_v1", as_of_time=as_of,
    )
    snapshot = derivatives_feature_pipeline.compute(request, history)

    assert snapshot.quality_status == FeatureQualityStatus.WARMING_UP
    assert all(v is None for v in snapshot.values.values())
    assert snapshot.quality_issues  # at least one WARMING_UP issue recorded


def test_compute_reports_valid_when_enough_history_for_every_calculator() -> None:
    as_of = BASE_TIME + timedelta(minutes=5 * 25)
    history = _rich_history(25, start=BASE_TIME)  # >= 20 (max required_lookback among the three)

    request = DerivativesFeatureComputationRequest(
        exchange="binance_usdm_futures", symbol=SYMBOL, feature_set="derivatives_v1", as_of_time=as_of,
    )
    snapshot = derivatives_feature_pipeline.compute(request, history)

    assert snapshot.quality_status == FeatureQualityStatus.VALID
    assert snapshot.values["funding_rate_zscore_20"] is not None
    assert snapshot.values["open_interest_roc_12"] is not None
    assert snapshot.quality_issues == []


def test_compute_lineage_sample_count_and_timestamps_are_honest() -> None:
    as_of = BASE_TIME + timedelta(minutes=5 * 10)
    history = _rich_history(10, start=BASE_TIME)

    request = DerivativesFeatureComputationRequest(
        exchange="binance_usdm_futures", symbol=SYMBOL, feature_set="derivatives_v1", as_of_time=as_of,
    )
    snapshot = derivatives_feature_pipeline.compute(request, history)

    assert snapshot.lineage.sample_count == 10
    assert snapshot.lineage.oldest_sample_timestamp == BASE_TIME
    assert snapshot.lineage.newest_sample_timestamp == history[-1].exchange_timestamp


def test_compute_with_no_history_is_warming_up_not_a_crash() -> None:
    request = DerivativesFeatureComputationRequest(
        exchange="binance_usdm_futures", symbol=SYMBOL, feature_set="derivatives_v1", as_of_time=BASE_TIME,
    )
    snapshot = derivatives_feature_pipeline.compute(request, [])
    assert snapshot.quality_status == FeatureQualityStatus.WARMING_UP
    assert snapshot.lineage.sample_count == 0
    assert snapshot.lineage.oldest_sample_timestamp is None
    assert snapshot.lineage.newest_sample_timestamp is None
