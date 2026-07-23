import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from packages.backtest.models import DatasetQualityStatus, HistoricalDatasetDefinition
from packages.market_data.historical_quality import TIMEFRAME_INTERVAL
from packages.market_data.models import Candle


class DatasetRegistry:
    """Historical Dataset Registry for dataset registration, checksum validation, and quality auditing."""

    def __init__(self) -> None:
        self.datasets: Dict[UUID, HistoricalDatasetDefinition] = {}
        self.dataset_candles: Dict[UUID, List[Candle]] = {}

    def compute_dataset_checksum(self, candles: List[Candle]) -> str:
        """Compute SHA256 checksum over normalized candle sequence."""
        hasher = hashlib.sha256()
        for c in candles:
            tf_val = c.timeframe.value if hasattr(c.timeframe, "value") else c.timeframe
            raw_str = (
                f"{c.symbol}:{tf_val}:{c.close_time.isoformat()}:"
                f"{c.open_price}:{c.high_price}:{c.low_price}:{c.close_price}:{c.volume}"
            )
            hasher.update(raw_str.encode("utf-8"))
        return hasher.hexdigest()

    def register_dataset(
        self,
        name: str,
        symbols: List[str],
        timeframes: List[str],
        candles: List[Candle],
        provider: str = "binance_public",
        exchange: str = "binance"
    ) -> HistoricalDatasetDefinition:
        """Validate and register an immutable historical dataset."""

        if not candles:
            raise ValueError("CANNOT_REGISTER_EMPTY_DATASET: Dataset must contain at least one candle")

        # 1. Quality Gate Check
        gap_count = 0
        duplicate_count = 0
        seen_timestamps = set()

        sorted_candles = sorted(candles, key=lambda c: c.close_time)

        for i, c in enumerate(sorted_candles):
            if c.close_time.tzinfo is None:
                raise ValueError("DATASET_QUALITY_ERROR: Timestamp must be UTC tz-aware")

            if c.close_time in seen_timestamps:
                duplicate_count += 1
            seen_timestamps.add(c.close_time)

            if i > 0:
                prev = sorted_candles[i - 1]
                if c.close_time < prev.close_time:
                    raise ValueError("DATASET_QUALITY_ERROR: Candles out of temporal order")

        # Real gap detection (previously always 0, regardless of actual spacing). Only computed
        # for single-timeframe datasets — every dataset registered by this codebase's callers
        # is single-timeframe in practice, and mixing intervals has no single "expected
        # spacing" to gap-check against.
        distinct_timeframes = {c.timeframe for c in sorted_candles}
        if len(distinct_timeframes) == 1:
            interval = TIMEFRAME_INTERVAL.get(next(iter(distinct_timeframes)))
            if interval is not None:
                for prev, cur in zip(sorted_candles, sorted_candles[1:], strict=False):
                    spacing = cur.close_time - prev.close_time
                    if spacing > interval and spacing % interval == timedelta(0):
                        missing = int(spacing / interval) - 1
                        if missing > 0:
                            gap_count += missing

        quality = DatasetQualityStatus.VALIDATED
        if duplicate_count > 0 or gap_count > 0:
            quality = DatasetQualityStatus.DEGRADED

        checksum = self.compute_dataset_checksum(sorted_candles)
        start_time = sorted_candles[0].close_time
        end_time = sorted_candles[-1].close_time
        now = datetime.now(timezone.utc)

        dataset_def = HistoricalDatasetDefinition(
            name=name,
            provider=provider,
            exchange=exchange,
            symbols=symbols,
            timeframes=timeframes,
            start_time=start_time,
            end_time=end_time,
            candle_count=len(sorted_candles),
            trade_count=0,
            checksum=checksum,
            quality_status=quality,
            gap_count=gap_count,
            duplicate_count=duplicate_count,
            created_at=now
        )

        self.datasets[dataset_def.dataset_id] = dataset_def
        self.dataset_candles[dataset_def.dataset_id] = sorted_candles
        return dataset_def

    def get_dataset(self, dataset_id: UUID) -> Optional[HistoricalDatasetDefinition]:
        return self.datasets.get(dataset_id)

    def get_dataset_candles(self, dataset_id: UUID) -> List[Candle]:
        return self.dataset_candles.get(dataset_id, [])


dataset_registry = DatasetRegistry()
