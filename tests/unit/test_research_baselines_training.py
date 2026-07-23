"""Unit tests for packages/research/{baselines,training}.py."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from packages.governance.decision_service import decision_service
from packages.market_data.models import Candle, DataQualityStatus, Timeframe
from packages.prediction.direction_model import LogisticRegressionDirectionModel
from packages.prediction.return_model import LinearReturnModel
from packages.research.baselines import BASELINE_NAMES, attach_baseline_decisions, compute_baseline_decisions
from packages.research.config import ModelConfig
from packages.research.exceptions import InsufficientDataError
from packages.research.models import SplitWindow
from packages.research.training import (
    build_model_artifact_record,
    prepare_training_matrix,
    train_linear_return_weights,
    train_logistic_direction_weights,
    weights_checksum,
)

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _uptrend_candles(n=60, start=Decimal("50000.00"), symbol="BTCUSDT", timeframe=Timeframe.H1):
    t0 = NOW - timedelta(hours=n)
    candles = []
    price = start
    for i in range(n):
        c_time = t0 + timedelta(hours=i)
        step = price * Decimal("0.005")
        open_p = price
        close_p = price + step
        candles.append(
            Candle(
                exchange="binance", symbol=symbol, timeframe=timeframe,
                open_time=c_time, close_time=c_time + timedelta(minutes=59),
                open_price=open_p, high_price=close_p + Decimal("10"), low_price=open_p - Decimal("10"),
                close_price=close_p, volume=Decimal("100.00"), trades_count=1000,
                exchange_timestamp=c_time + timedelta(minutes=59), data_quality_status=DataQualityStatus.HEALTHY,
                is_closed=True,
            )
        )
        price = close_p
    return candles


# --------------------------------------------------------------------------------------
# baselines
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_trade_and_buy_and_hold_are_trivial():
    candles = _uptrend_candles(60)
    entry_times = [c.open_time for c in candles[40:45]]
    decisions = await compute_baseline_decisions(candles, entry_times, "binance", "BTCUSDT", Timeframe.H1)

    for t in entry_times:
        assert decisions[t]["NO_TRADE"] is False
        assert decisions[t]["BUY_AND_HOLD"] is True


@pytest.mark.asyncio
async def test_trend_only_fires_long_on_a_clean_uptrend():
    candles = _uptrend_candles(60)
    entry_times = [candles[50].open_time]
    decisions = await compute_baseline_decisions(candles, entry_times, "binance", "BTCUSDT", Timeframe.H1)
    assert decisions[entry_times[0]]["TREND_ONLY"] is True


@pytest.mark.asyncio
async def test_multi_agent_no_ml_matches_decision_service_directly():
    candles = _uptrend_candles(60)
    entry_candle = candles[50]
    window = candles[: 51]

    result = await decision_service.decide(
        exchange="binance", symbol="BTCUSDT", timeframe=Timeframe.H1,
        candles=window, as_of_time=entry_candle.close_time, reference_price=entry_candle.close_price,
    )
    expected = result.trade_intent is not None

    decisions = await compute_baseline_decisions(candles, [entry_candle.open_time], "binance", "BTCUSDT", Timeframe.H1)
    assert decisions[entry_candle.open_time]["MULTI_AGENT_NO_ML"] == expected


def test_attach_baseline_decisions_adds_all_baseline_columns():
    candles = _uptrend_candles(60)
    label_table = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"] * 3,
            "timeframe": ["1h"] * 3,
            "entry_open_time": pd.to_datetime([c.open_time for c in candles[45:48]], utc=True),
        }
    )
    out = attach_baseline_decisions(label_table, candles)
    for name in BASELINE_NAMES:
        assert f"baseline__{name}" in out.columns
    assert len(out) == 3


def test_attach_baseline_decisions_empty_table():
    out = attach_baseline_decisions(pd.DataFrame(columns=["symbol", "timeframe", "entry_open_time"]), [])
    assert out.empty
    for name in BASELINE_NAMES:
        assert f"baseline__{name}" in out.columns


# --------------------------------------------------------------------------------------
# training
# --------------------------------------------------------------------------------------


def _synthetic_merged(n=200, seed=42):
    rng = np.random.default_rng(seed)
    feature_names = ["ema_20_slope", "rsi_14"]
    ema_slope = rng.normal(0, 0.01, n)
    rsi = rng.uniform(20, 80, n)
    # Construct a target correlated with ema_slope so the classifier has real signal.
    score = ema_slope * 50 + rng.normal(0, 0.05, n)
    label = np.where(score > 0.02, "PROFIT", np.where(score < -0.02, "LOSS", "TIMEOUT"))
    net_return_bps = score * 1000

    df = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"] * n,
            "timeframe": ["1h"] * n,
            "open_time": pd.date_range(NOW - timedelta(hours=n), periods=n, freq="h", tz=timezone.utc),
            "feature__ema_20_slope": ema_slope,
            "feature__rsi_14": rsi,
            "entry_open_time": pd.date_range(NOW - timedelta(hours=n), periods=n, freq="h", tz=timezone.utc),
            "horizon_minutes": [60] * n,
            "label": label,
            "net_return_bps": net_return_bps,
        }
    )
    return df, feature_names


def test_prepare_training_matrix_joins_on_symbol_timeframe_open_time():
    merged, feature_names = _synthetic_merged(n=20)
    feature_table = merged[["symbol", "timeframe", "open_time", "feature__ema_20_slope", "feature__rsi_14"]]
    label_table = merged[["symbol", "timeframe", "entry_open_time", "horizon_minutes", "label", "net_return_bps"]]

    joined = prepare_training_matrix(feature_table, label_table, feature_names, horizon_minutes=60)
    assert len(joined) == 20
    assert "feature__ema_20_slope" in joined.columns
    assert "label" in joined.columns


def test_train_logistic_direction_weights_produces_usable_weights():
    merged, feature_names = _synthetic_merged(n=300)
    weights = train_logistic_direction_weights(
        merged, feature_names, "logreg_test_v1", {"max_iter": 500}, random_seed=42
    )

    assert weights.feature_names == feature_names
    assert len(weights.up_coefficients) == len(feature_names)
    assert len(weights.down_coefficients) == len(feature_names)

    # Directly usable by the EXISTING inference model, no adapter needed.
    model = LogisticRegressionDirectionModel(weights)
    probs = model.predict_proba({"ema_20_slope": 0.02, "rsi_14": 50.0})
    assert 0.0 <= probs.probability_up <= 1.0
    assert 0.0 <= probs.probability_down <= 1.0


def test_train_logistic_direction_weights_raises_on_single_class():
    merged, feature_names = _synthetic_merged(n=50)
    merged = merged.copy()
    merged["label"] = "TIMEOUT"  # only one class present
    with pytest.raises(InsufficientDataError):
        train_logistic_direction_weights(merged, feature_names, "v1", {}, random_seed=42)


def test_train_logistic_direction_weights_raises_on_empty_input():
    _, feature_names = _synthetic_merged(n=1)
    empty = pd.DataFrame(columns=["feature__ema_20_slope", "feature__rsi_14", "label"])
    with pytest.raises(InsufficientDataError):
        train_logistic_direction_weights(empty, feature_names, "v1", {}, random_seed=42)


def test_train_linear_return_weights_produces_usable_weights():
    merged, feature_names = _synthetic_merged(n=300)
    weights = train_linear_return_weights(merged, feature_names, "linreg_test_v1")

    assert len(weights.coefficients) == len(feature_names)
    model = LinearReturnModel(weights)
    prediction = model.predict_expected_return_bps({"ema_20_slope": 0.02, "rsi_14": 50.0})
    assert isinstance(prediction, float)


def test_build_model_artifact_record_and_checksum_are_deterministic():
    merged, feature_names = _synthetic_merged(n=300)
    direction_weights = train_logistic_direction_weights(merged, feature_names, "v1", {"max_iter": 300}, random_seed=42)
    return_weights = train_linear_return_weights(merged, feature_names, "v1")

    checksum1 = weights_checksum(direction_weights, return_weights)
    checksum2 = weights_checksum(direction_weights, return_weights)
    assert checksum1 == checksum2

    window = SplitWindow(name="train", start=NOW - timedelta(days=10), end=NOW)
    record = build_model_artifact_record(
        model_config=ModelConfig(model_version="v1"),
        feature_version="standard_v1",
        dataset_checksum="abc123",
        label_version="triple_barrier_v1",
        train_window=window,
        validation_window=window,
        test_window=window,
        artifact_path="models/v1.weights.json",
        artifact_checksum=checksum1,
        config_hash="cfg-hash",
        now=NOW,
    )
    assert record.model_version == "v1"
    assert record.dataset_checksum == "abc123"
    assert record.artifact_checksum == checksum1
