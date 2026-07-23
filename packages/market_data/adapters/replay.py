from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncIterator, List, Sequence

from packages.market_data.models import (
    Candle,
    CandleUpdate,
    ExchangeInfo,
    MarketTrade,
    OrderBookDelta,
    OrderBookLevel,
    OrderBookSnapshot,
    SymbolInfo,
    Timeframe,
)
from packages.market_data.symbol_registry import symbol_registry


class ReplayMarketDataProvider:
    """Replay Market Data Provider that streams pre-loaded historical candles for backtesting or replay simulations."""

    def __init__(self, historical_candles: List[Candle], exchange_id: str = "binance_replay"):
        self.historical_candles = historical_candles
        self.exchange_id = exchange_id

    async def get_exchange_info(self) -> ExchangeInfo:
        return ExchangeInfo(
            exchange_id=self.exchange_id,
            name="Replay Market Data Provider",
            is_active=True
        )

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        info = symbol_registry.get_symbol_info(symbol)
        if not info:
            raise ValueError(f"Symbol '{symbol}' not found")
        return info

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int = 500,
    ) -> Sequence[Candle]:
        return [
            c for c in self.historical_candles
            if c.symbol == symbol and c.timeframe == timeframe and start_time <= c.open_time <= end_time
        ][:limit]

    async def fetch_order_book_snapshot(
        self,
        symbol: str,
        depth: int = 100,
    ) -> OrderBookSnapshot:
        now = datetime.now(timezone.utc)
        return OrderBookSnapshot(
            exchange=self.exchange_id,
            symbol=symbol,
            sequence_id=1,
            bids=[OrderBookLevel(price=Decimal("65000.00"), quantity=Decimal("1.0"))],
            asks=[OrderBookLevel(price=Decimal("65001.00"), quantity=Decimal("1.0"))],
            exchange_timestamp=now
        )

    async def stream_trades(self, symbols: Sequence[str]) -> AsyncIterator[MarketTrade]:
        if False:
            yield MarketTrade(...)

    async def stream_candles(
        self,
        symbols: Sequence[str],
        timeframes: Sequence[Timeframe],
    ) -> AsyncIterator[CandleUpdate]:
        for candle in self.historical_candles:
            if candle.symbol in symbols and candle.timeframe in timeframes:
                yield CandleUpdate(
                    exchange=self.exchange_id,
                    symbol=candle.symbol,
                    timeframe=candle.timeframe,
                    open_time=candle.open_time,
                    close_time=candle.close_time,
                    current_price=candle.close_price,
                    volume=candle.volume,
                    exchange_timestamp=candle.exchange_timestamp,
                    is_closed=True
                )

    async def stream_order_book(self, symbols: Sequence[str]) -> AsyncIterator[OrderBookDelta]:
        if False:
            yield OrderBookDelta(...)
