from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.market_data.models import Candle, OrderBookLevel, OrderBookSnapshot, Timeframe


def test_valid_candle_instantiation():
    now = datetime.now(timezone.utc)
    candle = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=Timeframe.M1,
        open_time=now,
        close_time=now,
        open_price=Decimal("65000.00"),
        high_price=Decimal("65100.00"),
        low_price=Decimal("64900.00"),
        close_price=Decimal("65050.00"),
        volume=Decimal("10.5"),
        exchange_timestamp=now
    )
    assert candle.high_price >= candle.open_price
    assert candle.low_price <= candle.close_price


def test_invalid_ohlc_high_price_raises_validation_error():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="Candle high_price must be >= open, close, and low prices"):
        Candle(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=Timeframe.M1,
            open_time=now,
            close_time=now,
            open_price=Decimal("65000.00"),
            high_price=Decimal("64000.00"),  # INVALID: smaller than open
            low_price=Decimal("63900.00"),
            close_price=Decimal("64500.00"),
            volume=Decimal("10.5"),
            exchange_timestamp=now
        )


def test_crossed_order_book_raises_error():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="Crossed order book detected"):
        OrderBookSnapshot(
            exchange="binance",
            symbol="BTC/USDT",
            sequence_id=100,
            bids=[OrderBookLevel(price=Decimal("65000.00"), quantity=Decimal("1.0"))],
            asks=[OrderBookLevel(price=Decimal("64999.00"), quantity=Decimal("1.0"))],  # INVALID: ask < bid
            exchange_timestamp=now
        )
