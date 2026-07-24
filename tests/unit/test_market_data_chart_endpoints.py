"""GET /market-data/candles (fixed to serve real historical OHLCV, no longer a synthetic
fixed-base-price loop) and GET /market-data/trend-projection (a technical EMA-20-slope
extrapolation, never a fabricated flat line when there isn't enough history) -- exercised
entirely offline by monkeypatching the module-level `_binance_provider.fetch_candles`, the
one real network call either endpoint makes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

import pytest
from fastapi.testclient import TestClient

import apps.api.routers.market_data as market_data_router
from apps.api.main import app
from packages.market_data.models import Candle, Timeframe

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


def test_trend_projection_available_for_a_clear_uptrend(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch_candles(monkeypatch, _rising_candles(40))
    with TestClient(app) as client:
        response = client.get(
            "/market-data/trend-projection", params={"symbol": SYMBOL, "timeframe": "1h", "projection_bars": 5}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["basis"] == "ema_20_slope"
    assert len(body["points"]) == 5
    # A clear, steady uptrend must yield a positive slope and a monotonically increasing
    # projected price path -- never a flat or arbitrary line.
    assert float(body["slope"]) > 0
    prices = [float(p["projected_price"]) for p in body["points"]]
    assert prices == sorted(prices)


def test_trend_projection_unavailable_with_insufficient_history(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch_candles(monkeypatch, _rising_candles(2))
    with TestClient(app) as client:
        response = client.get("/market-data/trend-projection", params={"symbol": SYMBOL, "timeframe": "1h"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["points"] == []


def test_trend_projection_unavailable_with_no_market_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fetch_candles(monkeypatch, [])
    with TestClient(app) as client:
        response = client.get("/market-data/trend-projection", params={"symbol": SYMBOL, "timeframe": "1h"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == "NO_MARKET_DATA_AVAILABLE"
