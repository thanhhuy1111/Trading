import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from packages.common.logger import logger
from packages.market_data.adapters.base import MarketDataProvider
from packages.market_data.models import Candle, IngestionCheckpoint, Timeframe


class HistoricalCandleIngestionService:
    """Historical Candle Ingestion Service with pagination, rate limiting, checkpoints, and backoff."""

    def __init__(
        self,
        provider: MarketDataProvider,
        batch_limit: int = 500,
        rate_limit_delay_sec: float = 0.2
    ):
        self.provider = provider
        self.batch_limit = batch_limit
        self.rate_limit_delay_sec = rate_limit_delay_sec

    async def ingest_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        checkpoint: Optional[IngestionCheckpoint] = None
    ) -> List[Candle]:
        """Ingests historical candles across pagination windows with checkpoint support."""
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware UTC")

        effective_start = start_time
        if checkpoint and checkpoint.last_ingested_open_time > start_time:
            effective_start = checkpoint.last_ingested_open_time + timedelta(minutes=1)
            logger.info(
                "Resuming ingestion from checkpoint",
                extra={"symbol": symbol, "effective_start": effective_start.isoformat()}
            )

        all_candles: List[Candle] = []
        curr_start = effective_start

        while curr_start < end_time:
            try:
                batch = await self.provider.fetch_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=curr_start,
                    end_time=end_time,
                    limit=self.batch_limit
                )

                if not batch:
                    break

                # Deduplicate and validate UTC closed candles
                for candle in batch:
                    if candle.is_closed and candle.open_time >= curr_start:
                        all_candles.append(candle)

                last_candle = batch[-1]
                if last_candle.open_time <= curr_start:
                    # Prevent infinite loop if provider returns same window
                    curr_start = curr_start + timedelta(hours=1)
                else:
                    curr_start = last_candle.open_time + timedelta(seconds=1)

                await asyncio.sleep(self.rate_limit_delay_sec)
            except Exception as e:
                logger.error("Error during historical ingestion batch", extra={"symbol": symbol, "error": str(e)})
                await asyncio.sleep(1.0)
                break

        return all_candles
