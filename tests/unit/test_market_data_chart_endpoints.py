"""GET /market-data/candles (fixed to serve real historical OHLCV, no longer a synthetic
fixed-base-price loop) and GET /market-data/trend-projection (real, walk-forward-validated
Ridge regression predictions from packages.retraining.price_projection -- never a fabricated
line when no trained-and-approved model artifact exists) -- exercised entirely offline by
monkeypatching the module-level `_binance_provider.fetch_candles` (the one real network call
either endpoint makes) and `artifact_path` (so tests never touch the real
data/research/price_models/ directory)."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient

import apps.api.routers.market_data as market_data_router
from apps.api.main import app
from packages.market_data.models import Candle, Timeframe
from packages.retraining.price_projection import FEATURE_NAMES

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"


def _rising_candles(n: int) -> List[Candle]:
    candles = []
    price = Decimal("50000")
    for i in range(n):
        ot = T0 + timedelta(hours=i)
        step = price * Decimal("0.01")
        candles.append(Candle(
            exchange="binance", symbol=SYMBOL, exchange_timestamp=ot, open_time=ot,
            close_time=ot + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1,
            open_price=price, high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), is_closed=True,
        ))
        price += step
    return candles


def _patch_fetch_candles(monkeypatch: pytest.MonkeyPatch, candles: List[Candle]) -> None:
    async def _fake_fetch_candles(symbol, timeframe, start_time, end_time, limit=500):
        return candles

    monkeypatch.setattr(market_data_router._binance_provider, "fetch_candles", _fake_fetch_candles)


def test_candles_endpoint_returns_real_sequential_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch_candles(monkeypatch, _rising_candles(5))
    with TestClient(app) as client:
        response = client.get("/market-data/candles", params={"symbol": SYMBOL, "timeframe": "1h", "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5

    # Every candle must have its OWN timestamp (the old synthetic endpoint stamped every
    # candle with the same `now`) and prices must vary bar to bar, not a fixed base+index.
    open_times = [c["open_time"] for c in body]
    assert len(set(open_times)) == 5
    assert open_times == sorted(open_times)
    close_prices = {c["close_price"] for c in body}
    assert len(close_prices) == 5


def test_candles_endpoint_returns_empty_list_on_adapter_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raising_fetch_candles(symbol, timeframe, start_time, end_time, limit=500):
        raise RuntimeError("BINANCE_UNREACHABLE")

    monkeypatch.setattr(market_data_router._binance_provider, "fetch_candles", _raising_fetch_candles)
    with TestClient(app) as client:
        response = client.get("/market-data/candles", params={"symbol": SYMBOL, "timeframe": "1h"})
    assert response.status_code == 200
    assert response.json() == []


def _write_fixture_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, horizon_1_approved: bool = True,
) -> Path:
    path = tmp_path / "BTCUSDT_1h.json"
    payload = {
        "symbol": SYMBOL, "timeframe": "1h", "trained_at": "2026-01-01T00:00:00+00:00",
        "dataset_checksum": "test", "code_commit": "test", "feature_names": FEATURE_NAMES,
        "horizons": {
            # Zero coefficients/intercept -> predicted_log_return == 0 -> projected_price ==
            # last_close exactly, so the test can assert an exact, easily-verified value
            # rather than reverse-computing the model's arithmetic.
            "1": {
                "approved": horizon_1_approved,
                "reason": "APPROVED" if horizon_1_approved else "FAILED_EVERY_FOLD_MUST_BEAT_NAIVE",
                "oos_mape": 0.001, "naive_oos_mape": 0.002, "oos_directional_accuracy": 0.6, "oos_trades": 50,
                "coefficients": [0.0] * len(FEATURE_NAMES) if horizon_1_approved else None,
                "intercept": 0.0 if horizon_1_approved else None,
                "feature_mean": [0.0] * len(FEATURE_NAMES) if horizon_1_approved else None,
                "feature_scale": [1.0] * len(FEATURE_NAMES) if horizon_1_approved else None,
            },
            "3": {
                "approved": False, "reason": "FAILED_MAPE_IMPROVEMENT", "oos_mape": 0.003, "naive_oos_mape": 0.002,
                "oos_directional_accuracy": 0.5, "oos_trades": 50,
                "coefficients": None, "intercept": None, "feature_mean": None, "feature_scale": None,
            },
        },
    }
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(market_data_router, "artifact_path", lambda symbol, timeframe: path)
    return path


def test_trend_projection_serves_only_approved_horizons_from_a_real_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_fetch_candles(monkeypatch, _rising_candles(40))
    _write_fixture_artifact(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.get(
            "/market-data/trend-projection", params={"symbol": SYMBOL, "timeframe": "1h", "projection_bars": 12}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["basis"] == "ridge_regression_v1"
    assert body["model_status"] == "PARTIAL"  # only 1 of 2 horizons in the fixture is approved
    # Only the approved horizon (1) is served -- the rejected one (3) must never appear.
    assert len(body["points"]) == 1
    assert body["points"][0]["horizon_bars"] == 1
    assert body["points"][0]["oos_mape"] == 0.001
    # Zero coefficients/intercept in the fixture -> predicted_log_return == 0 exactly.
    last_close = float(_rising_candles(40)[-1].close_price)
    assert abs(float(body["points"][0]["projected_price"]) - last_close) < 0.01


def test_forming_candle_cannot_change_served_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    closed = _rising_candles(40)
    forming = closed[-1].model_copy(
        update={
            "open_time": closed[-1].open_time + timedelta(hours=1),
            "close_time": closed[-1].close_time + timedelta(hours=1),
            "exchange_timestamp": closed[-1].exchange_timestamp + timedelta(hours=1),
            "close_price": Decimal("999999"),
            "high_price": Decimal("1000000"),
            "is_closed": False,
        }
    )
    _write_fixture_artifact(tmp_path, monkeypatch)

    _patch_fetch_candles(monkeypatch, closed)
    with TestClient(app) as client:
        base = client.get(
            "/market-data/trend-projection",
            params={"symbol": SYMBOL, "timeframe": "1h", "projection_bars": 12},
        ).json()

    _patch_fetch_candles(monkeypatch, [*closed, forming])
    with TestClient(app) as client:
        appended = client.get(
            "/market-data/trend-projection",
            params={"symbol": SYMBOL, "timeframe": "1h", "projection_bars": 12},
        ).json()

    assert appended["points"] == base["points"]


def test_trend_projection_unavailable_when_trained_but_no_horizon_approved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Distinct from "never trained": a model WAS trained and evaluated (this is exactly
    what the real BTCUSDT/1h training run produced -- every horizon honestly rejected on
    real out-of-sample data), so the caller must be able to tell that apart from a missing
    artifact, even though both are `available: false`."""
    _patch_fetch_candles(monkeypatch, _rising_candles(40))
    _write_fixture_artifact(tmp_path, monkeypatch, horizon_1_approved=False)
    with TestClient(app) as client:
        response = client.get("/market-data/trend-projection", params={"symbol": SYMBOL, "timeframe": "1h"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["model_status"] == "NO_APPROVED_MODEL"
    assert body["model_trained_at"] == "2026-01-01T00:00:00+00:00"
    assert body["points"] == []


def test_trend_projection_unavailable_when_no_artifact_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_fetch_candles(monkeypatch, _rising_candles(40))
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(market_data_router, "artifact_path", lambda symbol, timeframe: missing_path)
    with TestClient(app) as client:
        response = client.get("/market-data/trend-projection", params={"symbol": SYMBOL, "timeframe": "1h"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["model_status"] == "NO_TRAINED_MODEL"
    assert body["reason"] == "NO_TRAINED_MODEL"
    assert body["points"] == []


def test_trend_projection_unavailable_with_no_market_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch_candles(monkeypatch, [])
    with TestClient(app) as client:
        response = client.get("/market-data/trend-projection", params={"symbol": SYMBOL, "timeframe": "1h"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == "NO_MARKET_DATA_AVAILABLE"
