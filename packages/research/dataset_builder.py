"""Validates raw candles and builds an immutable, checksummed `RawCandleDataset` artifact.

Reuses `packages.market_data.guardian.data_guardian.validate_ohlc` for OHLC sanity (the
SAME check the live paper-trading path uses) rather than re-implementing candle
validation. No forward-filling of any kind is performed anywhere in this module -- a
missing candle is counted as a gap and left missing; this is a deliberate policy (silent
forward-fill would let a stale price masquerade as a fresh observation), not an oversight.
"""

from datetime import datetime, timezone
from typing import List, Tuple

from packages.market_data.guardian import data_guardian
from packages.market_data.models import Candle, Timeframe
from packages.recommendation.timeframes import TIMEFRAME_SECONDS
from packages.research.candle_repository import candles_to_dataframe
from packages.research.checksums import checksum_candles, get_code_commit
from packages.research.config import DatasetConfig
from packages.research.exceptions import DatasetValidationError
from packages.research.models import DatasetQualityStatus, RawCandleDataset


def build_raw_candle_dataset(
    candles: List[Candle],
    config: DatasetConfig,
    config_hash: str,
    now: datetime | None = None,
) -> Tuple[RawCandleDataset, List[Candle]]:
    """Returns (metadata, validated_sorted_candles). Raises DatasetValidationError if,
    after filtering, no usable candles remain.
    """
    eval_time = now or datetime.now(timezone.utc)
    issues: List[str] = []
    rejected_count = 0

    supported_symbols = set(config.symbols)
    supported_timeframes = set(config.timeframes)

    # 1. Filter: unsupported symbol/timeframe, not closed, future timestamp, bad OHLC.
    kept: List[Candle] = []
    for c in candles:
        tf_value = c.timeframe.value if hasattr(c.timeframe, "value") else str(c.timeframe)

        if c.symbol not in supported_symbols:
            rejected_count += 1
            continue
        if tf_value not in supported_timeframes:
            rejected_count += 1
            continue
        if not c.is_closed:
            rejected_count += 1
            continue
        if c.close_time > eval_time:
            # Defensive, mirrors packages.recommendation.service._fetch_candles: a
            # provider may mark a still-forming candle is_closed=True.
            rejected_count += 1
            continue
        if not data_guardian.validate_ohlc(c.open_price, c.high_price, c.low_price, c.close_price):
            rejected_count += 1
            continue
        if c.volume < 0:
            rejected_count += 1
            continue
        kept.append(c)

    if not kept:
        raise DatasetValidationError(
            f"No usable candles after validation (rejected {rejected_count} of {len(candles)})"
        )

    # 2. Deduplicate by (symbol, timeframe, open_time), keep first occurrence.
    seen: set = set()
    deduped: List[Candle] = []
    duplicate_count = 0
    for c in sorted(kept, key=lambda c: c.open_time):
        tf_value = c.timeframe.value if hasattr(c.timeframe, "value") else str(c.timeframe)
        key = (c.symbol, tf_value, c.open_time)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        deduped.append(c)

    # 3. Canonical chronological order (open_time is identity; already sorted above, but
    # sort explicitly per-symbol/timeframe group since a multi-symbol/timeframe list
    # interleaves).
    sorted_candles = sorted(deduped, key=lambda c: (c.symbol, str(c.timeframe), c.open_time))

    # 4. Gap detection per (symbol, timeframe) group -- informational, never forward-filled.
    gap_count = 0
    groups: dict = {}
    for c in sorted_candles:
        tf_value = c.timeframe.value if hasattr(c.timeframe, "value") else str(c.timeframe)
        groups.setdefault((c.symbol, tf_value), []).append(c)

    for (_symbol, tf_value), group_candles in groups.items():
        expected_step = TIMEFRAME_SECONDS.get(tf_value)
        if expected_step is None:
            continue
        for i in range(1, len(group_candles)):
            delta = (group_candles[i].open_time - group_candles[i - 1].open_time).total_seconds()
            if delta > expected_step * 1.5:
                gap_count += 1

    if duplicate_count > 0:
        issues.append(f"DUPLICATE_CANDLES_REMOVED:{duplicate_count}")
    if gap_count > 0:
        issues.append(f"GAPS_DETECTED:{gap_count}")
    if rejected_count > 0:
        issues.append(f"CANDLES_REJECTED:{rejected_count}")

    quality_status = (
        DatasetQualityStatus.DEGRADED if (duplicate_count > 0 or gap_count > 0) else DatasetQualityStatus.VALIDATED
    )

    checksum = checksum_candles(sorted_candles)
    dataset = RawCandleDataset(
        dataset_checksum=checksum,
        symbols=config.symbols,
        timeframes=config.timeframes,
        start_time=sorted_candles[0].open_time,
        end_time=sorted_candles[-1].close_time,
        candle_count=len(sorted_candles),
        source=config.source,
        source_version=config.source_version,
        created_at=eval_time,
        code_commit=get_code_commit(),
        config_hash=config_hash,
        duplicate_count=duplicate_count,
        rejected_count=rejected_count,
        quality_status=quality_status,
        quality_issues=issues,
    )
    return dataset, sorted_candles


__all__ = ["build_raw_candle_dataset", "candles_to_dataframe", "Timeframe"]
