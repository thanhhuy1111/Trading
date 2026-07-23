"""Unit tests for packages/research/{feature_dataset,labels}.py.

The leakage tests here are the most important tests in this phase: they prove a feature
computed at time T is never affected by candles that close after T, and that entry/exit
reference prices in labels come only from already-known candles at the moment they're used.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from packages.features.models import FeatureComputationRequest
from packages.features.pipeline import feature_pipeline
from packages.governance.cost_estimator import cost_estimator
from packages.market_data.models import Candle, DataQualityStatus, Timeframe
from packages.research.config import FeatureConfig, LabelConfig
from packages.research.feature_dataset import build_feature_table
from packages.research.labels import build_label_table

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _candle(symbol, timeframe, open_time, close_price, exchange="binance"):
    close_time = open_time + timedelta(hours=1)
    open_price = close_price - Decimal("2")
    return Candle(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open_price=open_price,
        high_price=max(open_price, close_price) + Decimal("1"),
        low_price=min(open_price, close_price) - Decimal("1"),
        close_price=close_price,
        volume=Decimal("100.0"),
        exchange_timestamp=close_time,
        data_quality_status=DataQualityStatus.HEALTHY,
        is_closed=True,
    )


def _uptrend_series(n, start_price=Decimal("50000.00"), symbol="BTCUSDT", timeframe=Timeframe.H1, t0=None):
    t0 = t0 or (NOW - timedelta(hours=n))
    candles = []
    price = start_price
    for i in range(n):
        open_time = t0 + timedelta(hours=i)
        step = price * Decimal("0.005")
        price = price + step
        candles.append(_candle(symbol, timeframe, open_time, price))
    return candles


def _flat_series(n, price=Decimal("50000.00"), symbol="BTCUSDT", timeframe=Timeframe.H1, t0=None):
    t0 = t0 or (NOW - timedelta(hours=n))
    return [_candle(symbol, timeframe, t0 + timedelta(hours=i), price) for i in range(n)]


# --------------------------------------------------------------------------------------
# feature_dataset: correctness + leakage
# --------------------------------------------------------------------------------------


def test_feature_table_matches_direct_feature_pipeline_call():
    candles = _uptrend_series(80)
    config = FeatureConfig(warmup_periods=60, lookback_window=300)
    table = build_feature_table(candles, config)

    assert not table.empty
    row = table.iloc[10]  # some arbitrary row past warmup
    as_of_time = row["close_time"].to_pydatetime()

    history = [c for c in candles if c.close_time <= as_of_time]
    request = FeatureComputationRequest(
        exchange="binance", symbol="BTCUSDT", timeframe=Timeframe.H1,
        feature_set=config.version, as_of_time=as_of_time,
    )
    snapshot = feature_pipeline.compute(request, history)

    assert row["feature__ema_20_slope"] == pytest.approx(float(snapshot.values["ema_20_slope"]), rel=1e-6)


def test_feature_table_skips_warmup_rows():
    candles = _uptrend_series(80)
    config = FeatureConfig(warmup_periods=60, lookback_window=300)
    table = build_feature_table(candles, config)
    assert len(table) == 80 - 60


def test_feature_table_is_deterministic():
    candles = _uptrend_series(80)
    config = FeatureConfig(warmup_periods=60, lookback_window=300)
    t1 = build_feature_table(candles, config)
    t2 = build_feature_table(candles, config)
    pd_testing_equal = (t1["feature__ema_20_slope"].to_numpy() == t2["feature__ema_20_slope"].to_numpy()).all()
    assert pd_testing_equal


def test_feature_table_never_changes_when_future_candles_are_appended():
    """LEAKAGE TEST: a feature value computed at as_of_time T must be byte-identical
    whether or not candles closing after T are present in the input.
    """
    candles = _uptrend_series(90)
    config = FeatureConfig(warmup_periods=60, lookback_window=300)

    table_short = build_feature_table(candles[:70], config)
    table_long = build_feature_table(candles, config)

    common_open_times = set(table_short["open_time"]) & set(table_long["open_time"])
    assert len(common_open_times) > 0

    short_indexed = table_short.set_index("open_time")
    long_indexed = table_long.set_index("open_time")
    for ot in common_open_times:
        assert short_indexed.loc[ot, "feature__ema_20_slope"] == pytest.approx(
            long_indexed.loc[ot, "feature__ema_20_slope"], rel=1e-9
        )
        assert short_indexed.loc[ot, "feature__rsi_14"] == pytest.approx(
            long_indexed.loc[ot, "feature__rsi_14"], rel=1e-9
        )


def test_feature_dataset_module_never_references_label_concepts():
    """Static guard: packages/research/feature_dataset.py must never import from
    packages.research.labels or reference label/barrier concepts in executable code."""
    import re

    src = Path("packages/research/feature_dataset.py").read_text(encoding="utf-8")
    code_only = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
    assert "labels" not in code_only.lower()
    assert "barrier" not in code_only.lower()


# --------------------------------------------------------------------------------------
# labels: triple-barrier correctness
# --------------------------------------------------------------------------------------


def test_labels_profit_when_upper_barrier_touched():
    candles = _uptrend_series(20)  # +0.5%/bar compounding -> comfortably breaks a 2% barrier
    config = LabelConfig(horizons_minutes=[300], upper_barrier_pct=Decimal("0.02"), lower_barrier_pct=Decimal("0.02"))
    table = build_label_table(candles, config)

    assert not table.empty
    first = table.iloc[0]
    assert first["first_barrier_hit"] == "UPPER"
    assert first["label"] == "PROFIT"
    assert first["net_return_bps"] > 0


def test_labels_loss_when_lower_barrier_touched():
    # A steady downtrend so price falls through the lower barrier.
    down_candles = [
        _candle(
            "BTCUSDT", Timeframe.H1,
            NOW - timedelta(hours=20) + timedelta(hours=i),
            Decimal("50000.00") - Decimal(i) * Decimal("300"),
        )
        for i in range(20)
    ]
    config = LabelConfig(horizons_minutes=[300], upper_barrier_pct=Decimal("0.02"), lower_barrier_pct=Decimal("0.02"))
    table = build_label_table(down_candles, config)

    assert not table.empty
    first = table.iloc[0]
    assert first["first_barrier_hit"] == "LOWER"
    assert first["label"] == "LOSS"


def test_labels_timeout_when_price_stays_within_barriers():
    candles = _flat_series(20)
    config = LabelConfig(horizons_minutes=[300], upper_barrier_pct=Decimal("0.05"), lower_barrier_pct=Decimal("0.05"))
    table = build_label_table(candles, config)

    assert not table.empty
    first = table.iloc[0]
    assert first["first_barrier_hit"] == "TIME"
    assert first["label"] == "TIMEOUT"


def test_labels_cost_can_flip_small_upper_touch_to_loss():
    # Tiny barrier (10bps) smaller than total round-trip cost (~22bps for BTCUSDT), so
    # even touching "UPPER" nets negative after costs.
    candles = _uptrend_series(20)
    cost_bps = cost_estimator.estimate_cost("BTCUSDT").total_cost_bps
    assert cost_bps > Decimal("10.0")  # sanity check on this test's own premise

    config = LabelConfig(horizons_minutes=[300], upper_barrier_pct=Decimal("0.001"), lower_barrier_pct=Decimal("0.001"))
    table = build_label_table(candles, config)
    assert not table.empty
    first = table.iloc[0]
    assert first["first_barrier_hit"] == "UPPER"
    assert first["label"] == "LOSS"
    assert first["net_return_bps"] < 0


def test_labels_skip_entries_without_enough_forward_history():
    candles = _flat_series(10)
    config = LabelConfig(horizons_minutes=[600], upper_barrier_pct=Decimal("0.05"), lower_barrier_pct=Decimal("0.05"))
    table = build_label_table(candles, config)
    # The last several entries cannot reach a 10h horizon within only 10 candles.
    assert len(table) < 10


def test_labels_use_only_entry_time_close_price_as_reference():
    candles = _uptrend_series(15)
    config = LabelConfig(horizons_minutes=[300], upper_barrier_pct=Decimal("0.05"), lower_barrier_pct=Decimal("0.05"))
    table = build_label_table(candles, config)
    first_row = table.iloc[0]
    matching_candle = next(c for c in candles if c.open_time == first_row["entry_open_time"].to_pydatetime())
    assert Decimal(first_row["entry_reference_price"]) == matching_candle.close_price


def test_labels_are_deterministic():
    candles = _uptrend_series(20)
    config = LabelConfig(horizons_minutes=[300], upper_barrier_pct=Decimal("0.02"), lower_barrier_pct=Decimal("0.02"))
    t1 = build_label_table(candles, config)
    t2 = build_label_table(candles, config)
    assert (t1["label"].to_numpy() == t2["label"].to_numpy()).all()
    assert (t1["net_return_bps"].to_numpy() == t2["net_return_bps"].to_numpy()).all()


def test_labels_module_never_imports_feature_dataset():
    """Static guard: labeling must not depend on feature computation -- they are
    independent pipeline stages, so a feature can never accidentally see a label."""
    import re

    src = Path("packages/research/labels.py").read_text(encoding="utf-8")
    code_only = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
    assert "feature_dataset" not in code_only
    assert "feature_pipeline" not in code_only
