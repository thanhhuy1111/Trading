from datetime import datetime
from typing import AsyncIterator, Protocol, Sequence

from packages.market_data.models import (
    Candle,
    CandleUpdate,
    ExchangeInfo,
    MarketTrade,
    OrderBookDelta,
    OrderBookSnapshot,
    SymbolInfo,
    Timeframe,
)


class MarketDataProvider(Protocol):
    """Read-only Async Interface for Exchange Market Data Providers.
    
    CRITICAL: MUST NOT CONTAIN ANY ORDER PLACEMENT OR PRIVATE ACCOUNT METHODS.
    """

    async def get_exchange_info(self) -> ExchangeInfo:
        ...

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        ...

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int = 500,
    ) -> Sequence[Candle]:
        ...

    async def fetch_order_book_snapshot(
        self,
        symbol: str,
        depth: int = 100,
    ) -> OrderBookSnapshot:
        ...

    async def stream_trades(
        self,
        symbols: Sequence[str],
    ) -> AsyncIterator[MarketTrade]:
        ...

    async def stream_candles(
        self,
        symbols: Sequence[str],
        timeframes: Sequence[Timeframe],
    ) -> AsyncIterator[CandleUpdate]:
        ...

    async def stream_order_book(
        self,
        symbols: Sequence[str],
    ) -> AsyncIterator[OrderBookDelta]:
        ...
