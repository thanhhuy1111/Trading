from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from packages.features.models import FeatureComputationRequest, FeatureSnapshot, Timeframe
from packages.features.pipeline import feature_pipeline
from packages.market_data.models import Candle


def make_closed_candle(close_p: str, dt: datetime) -> Candle:
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        open_time=dt,
        close_time=dt + timedelta(minutes=15),
        open_price=Decimal(close_p),
        high_price=Decimal(close_p) + Decimal("5.0"),
        low_price=Decimal(close_p) - Decimal("5.0"),
        close_price=Decimal(close_p),
        volume=Decimal("50.0"),
        is_closed=True,
        exchange_timestamp=dt
    )


def test_zero_lookahead_leakage_when_adding_future_candles():
    """Lookahead Leakage Test: Computing features at timestamp T produce IDENTICAL values.
    
    Even when 100 future candles (T+1 .. T+100) are appended to dataset.
    """
    base_time = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    historical_candles = [
        make_closed_candle(str(60000 + i * 10), base_time + timedelta(minutes=15 * i))
        for i in range(30)
    ]
    as_of_t = historical_candles[-1].close_time

    req = FeatureComputationRequest(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        feature_set="standard_v1",
        as_of_time=as_of_t
    )

    # 1. Compute snapshot at T using ONLY historical dataset up to T
    snapshot_original = feature_pipeline.compute(req, historical_candles)

    # 2. Append 100 future candles (T+1 .. T+100) to dataset
    future_candles = [
        make_closed_candle(str(70000 + i * 20), as_of_t + timedelta(minutes=15 * (i + 1)))
        for i in range(100)
    ]
    augmented_dataset = historical_candles + future_candles

    # 3. Compute snapshot again at SAME timestamp T using augmented dataset
    snapshot_augmented = feature_pipeline.compute(req, augmented_dataset)

    # 4. Invariant: Computed values at T must be 100% IDENTICAL
    assert snapshot_original.values == snapshot_augmented.values


def test_feature_snapshot_raises_error_on_future_lookback_end():
    """Lookahead Leakage Test: FeatureSnapshot enforces lookback_end <= as_of_time."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)

    with pytest.raises(ValueError, match="Lookahead Leakage Violation"):
        FeatureSnapshot(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=Timeframe.M15,
            feature_set="standard_v1",
            feature_set_version="1.0.0",
            event_time=future,
            as_of_time=now,  # INVALID: event_time > as_of_time
            computed_at=now,
            lookback_start=now,
            lookback_end=future,
            values={"return_1p": Decimal("0.01")},
            quality_status="VALID",
            quality_issues=[],
            source_data_version="v1",
            lineage={
                "source_exchange": "binance",
                "source_symbol": "BTC/USDT",
                "source_timeframe": "15m",
                "candle_count_used": 10,
                "oldest_candle_timestamp": now.isoformat(),
                "newest_candle_timestamp": future.isoformat(),
                "calculator_versions": {}
            }
        )
