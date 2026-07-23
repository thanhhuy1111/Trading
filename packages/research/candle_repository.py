"""Local candle cache + historical download, built on the EXISTING ingestion service.

Reuses `packages.market_data.ingestion.historical.HistoricalCandleIngestionService`
directly for pagination, rate-limit spacing, retry/backoff, and closed-candle filtering --
this module only adds local persistence (so re-running a download resumes instead of
re-fetching) and a deterministic on-disk shape (Parquet, sorted by open_time).

Raw downloaded candles live under `data/research/` (a mutable cache -- may be deleted and
re-downloaded at any time), which is distinct from an immutable, checksummed
`RawCandleDataset` artifact under `artifacts/datasets/` (built from a cache snapshot by
`packages.research.dataset_builder`). Both directories are gitignored; no market data is
ever committed to this repository.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd

from packages.common.logger import logger
from packages.market_data.adapters.base import MarketDataProvider
from packages.market_data.ingestion.historical import HistoricalCandleIngestionService
from packages.market_data.models import Candle, IngestionCheckpoint, Timeframe

DEFAULT_CACHE_ROOT = "data/research/candles"

_CANDLE_COLUMNS = [
    "exchange", "symbol", "timeframe", "open_time", "close_time",
    "open_price", "high_price", "low_price", "close_price",
    "volume", "quote_volume", "trades_count", "is_closed",
]


def candles_to_dataframe(candles: List[Candle]) -> pd.DataFrame:
    rows = [
        {
            "exchange": c.exchange,
            "symbol": c.symbol,
            "timeframe": c.timeframe.value if hasattr(c.timeframe, "value") else c.timeframe,
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
        }
        for c in candles
    ]
    return pd.DataFrame(rows, columns=_CANDLE_COLUMNS)


def dataframe_to_candles(df: pd.DataFrame) -> List[Candle]:
    from decimal import Decimal

    now = datetime.now(timezone.utc)
    candles = []
    for row in df.itertuples(index=False):
        candles.append(
            Candle(
                exchange=row.exchange,
                symbol=row.symbol,
                timeframe=Timeframe(row.timeframe),
                open_time=pd.Timestamp(row.open_time).to_pydatetime(),
                close_time=pd.Timestamp(row.close_time).to_pydatetime(),
                open_price=Decimal(row.open_price),
                high_price=Decimal(row.high_price),
                low_price=Decimal(row.low_price),
                close_price=Decimal(row.close_price),
                volume=Decimal(row.volume),
                quote_volume=Decimal(row.quote_volume),
                trades_count=int(row.trades_count),
                is_closed=bool(row.is_closed),
                exchange_timestamp=pd.Timestamp(row.close_time).to_pydatetime(),
                received_timestamp=now,
            )
        )
    return candles


class CandleRepository:
    def __init__(
        self,
        provider: MarketDataProvider,
        cache_root: str = DEFAULT_CACHE_ROOT,
        batch_limit: int = 500,
        rate_limit_delay_sec: float = 0.2,
    ) -> None:
        self._ingestion = HistoricalCandleIngestionService(provider, batch_limit, rate_limit_delay_sec)
        self._root = Path(cache_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, symbol: str, timeframe: Timeframe) -> Path:
        tf = timeframe.value if hasattr(timeframe, "value") else timeframe
        return self._root / f"{symbol}_{tf}.parquet"

    def _checkpoint_path(self, symbol: str, timeframe: Timeframe) -> Path:
        tf = timeframe.value if hasattr(timeframe, "value") else timeframe
        return self._root / f"{symbol}_{tf}.checkpoint.json"

    def load_cached(self, symbol: str, timeframe: Timeframe) -> Optional[pd.DataFrame]:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def _load_checkpoint(self, symbol: str, timeframe: Timeframe) -> Optional[IngestionCheckpoint]:
        path = self._checkpoint_path(symbol, timeframe)
        if not path.exists():
            return None
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        return IngestionCheckpoint(
            exchange=raw["exchange"],
            symbol=raw["symbol"],
            timeframe=Timeframe(raw["timeframe"]),
            last_ingested_open_time=datetime.fromisoformat(raw["last_ingested_open_time"]),
        )

    def _save_checkpoint(self, checkpoint: IngestionCheckpoint) -> None:
        path = self._checkpoint_path(checkpoint.symbol, checkpoint.timeframe)
        path.write_text(
            checkpoint.model_dump_json(indent=2),
            encoding="utf-8",
        )

    async def download(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
        resume: bool = True,
    ) -> pd.DataFrame:
        """Downloads (or resumes downloading) closed candles into the local cache and
        returns the full, deduplicated, chronologically sorted cache contents for this
        symbol/timeframe (not just the newly fetched slice).
        """
        checkpoint = self._load_checkpoint(symbol, timeframe) if resume else None
        new_candles = await self._ingestion.ingest_candles(symbol, timeframe, start_time, end_time, checkpoint)

        new_df = candles_to_dataframe(new_candles)
        existing_df = self.load_cached(symbol, timeframe)
        if existing_df is not None and not existing_df.empty:
            combined = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined = new_df

        if not combined.empty:
            combined = combined.drop_duplicates(subset=["open_time"], keep="last")
            combined = combined.sort_values("open_time").reset_index(drop=True)
            combined.to_parquet(self._cache_path(symbol, timeframe), index=False)

            last_open_time = pd.Timestamp(combined["open_time"].iloc[-1]).to_pydatetime()
            self._save_checkpoint(
                IngestionCheckpoint(
                    exchange=new_candles[0].exchange if new_candles else "binance",
                    symbol=symbol,
                    timeframe=timeframe,
                    last_ingested_open_time=last_open_time,
                )
            )

        logger.info(
            "research_candle_download_complete",
            extra={
                "symbol": symbol,
                "timeframe": str(timeframe),
                "new_candles": len(new_candles),
                "cache_rows": len(combined),
            },
        )
        return combined
