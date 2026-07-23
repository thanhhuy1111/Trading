from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncIterator, Sequence

from packages.market_data.models import (
    Candle,
    CandleUpdate,
    DataQualityStatus,
    ExchangeInfo,
    MarketTrade,
    OrderBookDelta,
    OrderBookLevel,
    OrderBookSnapshot,
    SymbolInfo,
    Timeframe,
)
from packages.market_data.symbol_registry import symbol_registry


class MockMarketDataProvider:
    """Mock Market Data Provider for unit tests and local simulation without external network calls."""

    def __init__(self, exchange_id: str = "mock_binance"):
        self.exchange_id = exchange_id

    async def get_exchange_info(self) -> ExchangeInfo:
        return ExchangeInfo(
            exchange_id=self.exchange_id,
            name="Mock Binance Exchange",
            is_active=True
        )

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        info = symbol_registry.get_symbol_info(symbol)
        if not info:
            raise ValueError(f"Symbol '{symbol}' not found in registry")
        return info

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int = 500,
    ) -> Sequence[Candle]:
        candles = []
        current_time = start_time
        base_price = Decimal("65000.00") if "BTC" in symbol else Decimal("3500.00")
        interval_minutes = 1 if timeframe == Timeframe.M1 else 5

        while current_time < end_time and len(candles) < limit:
            close_time = current_time + timedelta(minutes=interval_minutes)
            candles.append(
                Candle(
                    exchange=self.exchange_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=current_time,
                    close_time=close_time,
                    open_price=base_price,
                    high_price=base_price + Decimal("10.00"),
                    low_price=base_price - Decimal("5.00"),
                    close_price=base_price + Decimal("2.00"),
                    volume=Decimal("12.5"),
                    exchange_timestamp=close_time,
                    data_quality_status=DataQualityStatus.HEALTHY,
                    is_closed=True,
                )
            )
            current_time = close_time
            base_price += Decimal("1.50")

        return candles

    async def fetch_order_book_snapshot(
        self,
        symbol: str,
        depth: int = 100,
    ) -> OrderBookSnapshot:
        now = datetime.now(timezone.utc)
        base_price = Decimal("65000.00") if "BTC" in symbol else Decimal("3500.00")
        return OrderBookSnapshot(
            exchange=self.exchange_id,
            symbol=symbol,
            sequence_id=10001,
            bids=[OrderBookLevel(price=base_price - Decimal("1.00"), quantity=Decimal("1.5"))],
            asks=[OrderBookLevel(price=base_price + Decimal("1.00"), quantity=Decimal("2.0"))],
            exchange_timestamp=now
        )

    async def stream_trades(
        self,
        symbols: Sequence[str],
    ) -> AsyncIterator[MarketTrade]:
        now = datetime.now(timezone.utc)
        for symbol in symbols:
            yield MarketTrade(
                exchange=self.exchange_id,
                symbol=symbol,
                trade_id="mock_tr_1",
                price=Decimal("65000.00"),
                quantity=Decimal("0.5"),
                side="BUY",
                exchange_timestamp=now
            )

    async def stream_candles(
        self,
        symbols: Sequence[str],
        timeframes: Sequence[Timeframe],
    ) -> AsyncIterator[CandleUpdate]:
        now = datetime.now(timezone.utc)
        for symbol in symbols:
            for tf in timeframes:
                yield CandleUpdate(
                    exchange=self.exchange_id,
                    symbol=symbol,
                    timeframe=tf,
                    open_time=now - timedelta(minutes=1),
                    close_time=now,
                    current_price=Decimal("65000.00"),
                    volume=Decimal("1.2"),
                    exchange_timestamp=now,
                    is_closed=False
                )

    async def stream_order_book(
        self,
        symbols: Sequence[str],
    ) -> AsyncIterator[OrderBookDelta]:
        now = datetime.now(timezone.utc)
        for symbol in symbols:
            yield OrderBookDelta(
                exchange=self.exchange_id,
                symbol=symbol,
                first_update_id=10002,
                final_update_id=10003,
                bids=[OrderBookLevel(price=Decimal("64999.00"), quantity=Decimal("1.0"))],
                asks=[OrderBookLevel(price=Decimal("65001.00"), quantity=Decimal("1.0"))],
                exchange_timestamp=now
            )
