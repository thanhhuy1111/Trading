"""Offline tests for BinancePublicFuturesDataProvider -- mocks `_get_json` (the one method
that actually makes an HTTP call) so these never touch the real network, mirroring how
tests/unit/test_market_data_chart_endpoints.py mocks the spot adapter's fetch_candles."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

import pytest

from packages.market_data.adapters.binance_futures import BinancePublicFuturesDataProvider
from packages.market_data.models import DataQualityStatus

SYMBOL = "BTC/USDT"


def _premium_index_response(funding_rate: str = "0.0001") -> Dict[str, Any]:
    return {
        "symbol": "BTCUSDT", "markPrice": "50100.00", "indexPrice": "50000.00",
        "lastFundingRate": funding_rate, "nextFundingTime": 1893456000000, "time": 1893427200000,
    }


def _open_interest_response() -> Dict[str, Any]:
    return {"symbol": "BTCUSDT", "openInterest": "12345.678", "time": 1893427200000}


def _long_short_ratio_response() -> List[Dict[str, Any]]:
    return [{
        "symbol": "BTCUSDT", "longShortRatio": "1.5", "longAccount": "0.6", "shortAccount": "0.4",
        "timestamp": 1893427200000,
    }]


def _taker_ratio_response() -> List[Dict[str, Any]]:
    return [{"buySellRatio": "1.1", "buyVol": "100", "sellVol": "91", "timestamp": 1893427200000}]


async def test_fetch_mark_and_index_price_parses_real_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        assert path == "/fapi/v1/premiumIndex"
        return _premium_index_response()

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    result = await provider.fetch_mark_and_index_price(SYMBOL)
    assert result is not None
    assert result["mark_price"] == Decimal("50100.00")
    assert result["index_price"] == Decimal("50000.00")
    assert result["funding_rate"] == Decimal("0.0001")
    assert result["next_funding_time"].tzinfo is not None


async def test_fetch_mark_and_index_price_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _raising(path: str, params: Dict[str, str]) -> Any:
        raise RuntimeError("BINANCE_FUTURES_UNREACHABLE")

    monkeypatch.setattr(provider, "_get_json", _raising)
    assert await provider.fetch_mark_and_index_price(SYMBOL) is None


async def test_fetch_open_interest_parses_real_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        assert path == "/fapi/v1/openInterest"
        return _open_interest_response()

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    result = await provider.fetch_open_interest(SYMBOL)
    assert result == {
        "open_interest": Decimal("12345.678"),
        "as_of": datetime.fromtimestamp(1893427200000 / 1000.0, tz=timezone.utc),
    }


async def test_fetch_long_short_ratio_uses_latest_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        assert path == "/futures/data/globalLongShortAccountRatio"
        return _long_short_ratio_response()

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    result = await provider.fetch_long_short_ratio(SYMBOL)
    assert result is not None
    assert result["long_short_account_ratio"] == Decimal("1.5")


async def test_fetch_long_short_ratio_returns_none_on_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        return []

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    assert await provider.fetch_long_short_ratio(SYMBOL) is None


async def test_fetch_taker_buy_sell_ratio_parses_real_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        assert path == "/futures/data/takerlongshortRatio"
        return _taker_ratio_response()

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    result = await provider.fetch_taker_buy_sell_ratio(SYMBOL)
    assert result is not None
    assert result["taker_buy_sell_ratio"] == Decimal("1.1")


async def test_fetch_snapshot_all_succeed_is_healthy_with_basis_computed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        if path == "/fapi/v1/premiumIndex":
            return _premium_index_response()
        if path == "/fapi/v1/openInterest":
            return _open_interest_response()
        if path == "/futures/data/globalLongShortAccountRatio":
            return _long_short_ratio_response()
        if path == "/futures/data/takerlongshortRatio":
            return _taker_ratio_response()
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    snapshot = await provider.fetch_snapshot(SYMBOL, spot_reference_price=Decimal("50000"))

    assert snapshot.data_quality_status == DataQualityStatus.HEALTHY
    assert snapshot.mark_price == Decimal("50100.00")
    assert snapshot.open_interest == Decimal("12345.678")
    assert snapshot.long_short_account_ratio == Decimal("1.5")
    assert snapshot.taker_buy_sell_ratio == Decimal("1.1")
    assert snapshot.futures_basis_bps is not None
    assert snapshot.open_interest_change_pct is None  # deliberately deferred, see module docstring
    assert snapshot.reason_codes == []


async def test_fetch_snapshot_without_spot_price_has_no_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        if path == "/fapi/v1/premiumIndex":
            return _premium_index_response()
        return []

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    snapshot = await provider.fetch_snapshot(SYMBOL)  # no spot_reference_price supplied
    assert snapshot.mark_price is not None
    assert snapshot.futures_basis_bps is None


async def test_fetch_snapshot_partial_failure_is_degraded_never_fabricated(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _fake_get_json(path: str, params: Dict[str, str]) -> Any:
        if path == "/fapi/v1/premiumIndex":
            return _premium_index_response()
        if path == "/fapi/v1/openInterest":
            raise RuntimeError("endpoint down")
        if path == "/futures/data/globalLongShortAccountRatio":
            return _long_short_ratio_response()
        if path == "/futures/data/takerlongshortRatio":
            return _taker_ratio_response()
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(provider, "_get_json", _fake_get_json)
    snapshot = await provider.fetch_snapshot(SYMBOL)

    assert snapshot.data_quality_status == DataQualityStatus.DEGRADED
    assert snapshot.mark_price is not None
    assert snapshot.open_interest is None  # never fabricated -- stays null
    assert any("open_interest" in code for code in snapshot.reason_codes)


async def test_fetch_snapshot_total_failure_is_unhealthy_with_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BinancePublicFuturesDataProvider()

    async def _raising(path: str, params: Dict[str, str]) -> Any:
        raise RuntimeError("BINANCE_FUTURES_UNREACHABLE")

    monkeypatch.setattr(provider, "_get_json", _raising)
    snapshot = await provider.fetch_snapshot(SYMBOL, spot_reference_price=Decimal("50000"))

    assert snapshot.data_quality_status == DataQualityStatus.UNHEALTHY
    assert snapshot.mark_price is None
    assert snapshot.open_interest is None
    assert snapshot.long_short_account_ratio is None
    assert snapshot.taker_buy_sell_ratio is None
    assert snapshot.futures_basis_bps is None
    assert "ALL_DERIVATIVES_SUB_FETCHES_FAILED" in snapshot.reason_codes
