import asyncio
import json
import ssl
from datetime import datetime, timedelta, timezone

import pytest

from packages.market_data.adapters.binance import (
    BinancePublicMarketDataProvider,
    _get_ssl_context,
)
from packages.market_data.adapters.mock import MockMarketDataProvider
from packages.market_data.adapters.replay import ReplayMarketDataProvider
from packages.market_data.models import Timeframe


def test_market_data_adapters_have_no_order_execution_methods():
    """Safety Test: Proves that exchange market data providers contain NO order placement or private API methods."""
    prohibited_substrings = ["create_order", "place_order", "cancel_order", "submit_order", "buy", "sell", "private"]

    for provider_cls in [BinancePublicMarketDataProvider, MockMarketDataProvider, ReplayMarketDataProvider]:
        method_names = [m for m in dir(provider_cls) if not m.startswith("__")]
        for m in method_names:
            for prohibited in prohibited_substrings:
                msg = f"Safety Violation: Provider '{provider_cls.__name__}' contains method '{m}'"
                assert prohibited not in m.lower(), msg


def test_binance_public_adapter_verifies_tls_certificates() -> None:
    context = _get_ssl_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_binance_adapter_marks_forming_candle_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 7, 24, 8, tzinfo=timezone.utc)
    first_close = start + timedelta(hours=1) - timedelta(milliseconds=1)
    second_close = start + timedelta(hours=2) - timedelta(milliseconds=1)
    requested_at = start + timedelta(hours=1, minutes=30)
    rows = [
        [
            int(start.timestamp() * 1000),
            "100",
            "110",
            "90",
            "105",
            "10",
            int(first_close.timestamp() * 1000),
            "1000",
            20,
        ],
        [
            int((start + timedelta(hours=1)).timestamp() * 1000),
            "105",
            "115",
            "95",
            "108",
            "12",
            int(second_close.timestamp() * 1000),
            "1200",
            25,
        ],
    ]

    class FakeResponse:
        def read(self) -> bytes:
            return json.dumps(rows).encode()

    monkeypatch.setattr(
        "packages.market_data.adapters.binance.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    candles = asyncio.run(
        BinancePublicMarketDataProvider().fetch_candles(
            "BTC/USDT",
            Timeframe.H1,
            start,
            requested_at,
            limit=2,
        )
    )

    assert [candle.is_closed for candle in candles] == [True, False]
