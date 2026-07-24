"""GET /market-data/derivatives/{symbol} -- exercised entirely offline by monkeypatching the
module-level `_futures_provider.fetch_snapshot` and `_binance_provider.fetch_current_prices`
(the two real network calls this endpoint makes), following the same convention as
tests/unit/test_market_data_chart_endpoints.py."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import apps.api.routers.market_data as market_data_router
from apps.api.main import app
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.models import DataQualityStatus

SYMBOL = "BTC/USDT"


def _healthy_snapshot() -> DerivativesSnapshot:
    return DerivativesSnapshot(
        exchange="binance_usdm_futures", symbol=SYMBOL, exchange_timestamp=datetime.now(timezone.utc),
        data_quality_status=DataQualityStatus.HEALTHY, mark_price=Decimal("50100"), index_price=Decimal("50000"),
        funding_rate=Decimal("0.0001"), next_funding_time=datetime.now(timezone.utc),
        open_interest=Decimal("12345.678"), long_short_account_ratio=Decimal("1.5"),
        taker_buy_sell_ratio=Decimal("1.1"), futures_basis_bps=Decimal("20"), reason_codes=[],
    )


def _patch_futures_provider(monkeypatch: pytest.MonkeyPatch, snapshot: DerivativesSnapshot) -> None:
    async def _fake_fetch_snapshot(symbol: str, spot_reference_price=None) -> DerivativesSnapshot:
        return snapshot

    monkeypatch.setattr(market_data_router._futures_provider, "fetch_snapshot", _fake_fetch_snapshot)


def _patch_spot_price(monkeypatch: pytest.MonkeyPatch, price: Decimal) -> None:
    async def _fake_fetch_current_prices(symbols):
        return {s: price for s in symbols}

    monkeypatch.setattr(market_data_router._binance_provider, "fetch_current_prices", _fake_fetch_current_prices)


def test_derivatives_endpoint_returns_real_snapshot_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    market_data_router._derivatives_cache.clear()
    _patch_spot_price(monkeypatch, Decimal("50000"))
    _patch_futures_provider(monkeypatch, _healthy_snapshot())
    with TestClient(app) as client:
        response = client.get(f"/market-data/derivatives/{SYMBOL}")
    assert response.status_code == 200
    body = response.json()
    assert body["data_quality_status"] == "HEALTHY"
    assert body["mark_price"] == "50100"
    assert body["open_interest"] == "12345.678"
    assert body["long_short_account_ratio"] == "1.5"
    assert body["taker_buy_sell_ratio"] == "1.1"
    assert body["futures_basis_bps"] == "20"
    assert body["reason_codes"] == []


def test_derivatives_endpoint_partial_failure_never_fabricates_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    market_data_router._derivatives_cache.clear()
    _patch_spot_price(monkeypatch, Decimal("50000"))
    degraded = DerivativesSnapshot(
        exchange="binance_usdm_futures", symbol=SYMBOL, exchange_timestamp=datetime.now(timezone.utc),
        data_quality_status=DataQualityStatus.DEGRADED, mark_price=Decimal("50100"), open_interest=None,
        reason_codes=["PARTIAL_DATA_MISSING:['open_interest']"],
    )
    _patch_futures_provider(monkeypatch, degraded)
    with TestClient(app) as client:
        response = client.get(f"/market-data/derivatives/{SYMBOL}")
    assert response.status_code == 200
    body = response.json()
    assert body["data_quality_status"] == "DEGRADED"
    assert body["open_interest"] is None
    assert body["reason_codes"]


def test_derivatives_endpoint_serves_from_cache_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    market_data_router._derivatives_cache.clear()
    _patch_spot_price(monkeypatch, Decimal("50000"))
    call_count = {"n": 0}

    async def _counting_fetch_snapshot(symbol: str, spot_reference_price=None) -> DerivativesSnapshot:
        call_count["n"] += 1
        return _healthy_snapshot()

    monkeypatch.setattr(market_data_router._futures_provider, "fetch_snapshot", _counting_fetch_snapshot)
    with TestClient(app) as client:
        first = client.get(f"/market-data/derivatives/{SYMBOL}")
        second = client.get(f"/market-data/derivatives/{SYMBOL}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count["n"] == 1  # second request served from the TTL cache, no new fetch
