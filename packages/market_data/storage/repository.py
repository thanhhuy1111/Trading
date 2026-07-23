from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.market_data.models import (
    Candle,
    IngestionCheckpoint,
    MarketDataHealth,
    MarketTrade,
    OrderBookSnapshot,
    Timeframe,
)


class CandleRepository:
    """PostgreSQL repository for storing and querying historical candles."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_candles(self, candles: List[Candle]) -> int:
        """Batch upserts candles with ON CONFLICT (exchange, symbol, timeframe, open_time) DO NOTHING."""
        if not candles:
            return 0

        query = text("""
            INSERT INTO candles (
                id, exchange, symbol, timeframe, open_time, close_time,
                open_price, high_price, low_price, close_price, volume,
                quote_volume, trades_count, is_closed, created_at
            ) VALUES (
                :id, :exchange, :symbol, :timeframe, :open_time, :close_time,
                :open_price, :high_price, :low_price, :close_price, :volume,
                :quote_volume, :trades_count, :is_closed, NOW()
            )
            ON CONFLICT (exchange, symbol, timeframe, open_time) DO UPDATE SET
                close_price = EXCLUDED.close_price,
                high_price = GREATEST(candles.high_price, EXCLUDED.high_price),
                low_price = LEAST(candles.low_price, EXCLUDED.low_price),
                volume = EXCLUDED.volume,
                is_closed = EXCLUDED.is_closed
        """)

        params = []
        for c in candles:
            params.append({
                "id": uuid4(),
                "exchange": c.exchange,
                "symbol": c.symbol,
                "timeframe": c.timeframe.value,
                "open_time": c.open_time,
                "close_time": c.close_time,
                "open_price": str(c.open_price),
                "high_price": str(c.high_price),
                "low_price": str(c.low_price),
                "close_price": str(c.close_price),
                "volume": str(c.volume),
                "quote_volume": str(c.quote_volume),
                "trades_count": c.trades_count,
                "is_closed": c.is_closed,
            })

        await self.session.execute(query, params)
        return len(candles)

    async def query_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        limit: int = 500
    ) -> List[Candle]:
        """Queries stored candles in timeframe and window."""
        query = text("""
            SELECT exchange, symbol, timeframe, open_time, close_time,
                   open_price, high_price, low_price, close_price, volume,
                   quote_volume, trades_count, is_closed, created_at
            FROM candles
            WHERE symbol = :symbol AND timeframe = :timeframe
              AND open_time >= :start_time AND open_time <= :end_time
            ORDER BY open_time ASC
            LIMIT :limit
        """)
        res = await self.session.execute(
            query,
            {
                "symbol": symbol,
                "timeframe": timeframe.value,
                "start_time": start_time,
                "end_time": end_time,
                "limit": limit
            }
        )
        rows = res.mappings().all()

        candles = []
        for r in rows:
            candles.append(Candle(
                exchange=r["exchange"],
                symbol=r["symbol"],
                timeframe=Timeframe(r["timeframe"]),
                open_time=r["open_time"],
                close_time=r["close_time"],
                open_price=Decimal(str(r["open_price"])),
                high_price=Decimal(str(r["high_price"])),
                low_price=Decimal(str(r["low_price"])),
                close_price=Decimal(str(r["close_price"])),
                volume=Decimal(str(r["volume"])),
                quote_volume=Decimal(str(r["quote_volume"])),
                trades_count=r["trades_count"],
                exchange_timestamp=r["close_time"],
                is_closed=r["is_closed"]
            ))
        return candles


class TradeRepository:
    """Repository for public market trades."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_trade(self, trade: MarketTrade) -> UUID:
        trade_id = uuid4()
        return trade_id


class OrderBookRepository:
    """Repository for order book snapshots."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_snapshot(self, snapshot: OrderBookSnapshot) -> UUID:
        snap_id = uuid4()
        return snap_id


class MarketDataHealthRepository:
    """Repository for market data health status tracking."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def update_health(self, health: MarketDataHealth) -> None:
        query = text("""
            INSERT INTO market_data_health (
                exchange, symbol, trades_status, candles_status, order_book_status,
                overall_status, last_trade_at, last_candle_at, last_order_book_at, updated_at
            ) VALUES (
                :exchange, :symbol, :trades_status, :candles_status, :order_book_status,
                :overall_status, :last_trade_at, :last_candle_at, :last_order_book_at, NOW()
            )
            ON CONFLICT (exchange, symbol) DO UPDATE SET
                trades_status = EXCLUDED.trades_status,
                candles_status = EXCLUDED.candles_status,
                order_book_status = EXCLUDED.order_book_status,
                overall_status = EXCLUDED.overall_status,
                updated_at = NOW()
        """)
        await self.session.execute(
            query,
            {
                "exchange": health.exchange,
                "symbol": health.symbol,
                "trades_status": health.trades_status.value,
                "candles_status": health.candles_status.value,
                "order_book_status": health.order_book_status.value,
                "overall_status": health.overall_status.value,
                "last_trade_at": health.last_trade_at,
                "last_candle_at": health.last_candle_at,
                "last_order_book_at": health.last_order_book_at,
            }
        )


class IngestionCheckpointRepository:
    """Repository for ingestion checkpoints."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_checkpoint(self, exchange: str, symbol: str, timeframe: Timeframe) -> Optional[IngestionCheckpoint]:
        query = text("""
            SELECT id, exchange, symbol, timeframe, last_ingested_open_time, updated_at
            FROM ingestion_checkpoints
            WHERE exchange = :exchange AND symbol = :symbol AND timeframe = :timeframe
        """)
        res = await self.session.execute(
            query,
            {"exchange": exchange, "symbol": symbol, "timeframe": timeframe.value}
        )
        row = res.mappings().first()
        if not row:
            return None
        return IngestionCheckpoint(
            id=row["id"],
            exchange=row["exchange"],
            symbol=row["symbol"],
            timeframe=Timeframe(row["timeframe"]),
            last_ingested_open_time=row["last_ingested_open_time"],
            updated_at=row["updated_at"]
        )

    async def save_checkpoint(self, checkpoint: IngestionCheckpoint) -> None:
        query = text("""
            INSERT INTO ingestion_checkpoints (
                id, exchange, symbol, timeframe, last_ingested_open_time, updated_at
            ) VALUES (
                :id, :exchange, :symbol, :timeframe, :last_ingested_open_time, NOW()
            )
            ON CONFLICT (exchange, symbol, timeframe) DO UPDATE SET
                last_ingested_open_time = EXCLUDED.last_ingested_open_time,
                updated_at = NOW()
        """)
        await self.session.execute(
            query,
            {
                "id": checkpoint.id,
                "exchange": checkpoint.exchange,
                "symbol": checkpoint.symbol,
                "timeframe": checkpoint.timeframe.value,
                "last_ingested_open_time": checkpoint.last_ingested_open_time,
            }
        )
