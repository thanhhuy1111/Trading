"""Phase 4.4: baseline rolling-correlation service.

Computed from real point-in-time historical returns (Pearson correlation over aligned
close-to-close returns) — never a placeholder. `correlation=None` (never 0.0) whenever the
sample is too small or data is missing (Section 9.4: "no missing-correlation-as-zero
behavior") — a caller that treats None as "uncorrelated" is making its own choice; this
service never makes that choice for it.
"""

import statistics
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, List, Optional

from packages.domain.entities import CorrelationSnapshot
from packages.market_data.models import Candle, Timeframe

CORRELATION_WINDOW_VERSION = "corr_v1"
DEFAULT_WINDOW_BARS = 90
DEFAULT_MINIMUM_SAMPLE_COUNT = 30
DEFAULT_MAX_STALENESS = timedelta(hours=4)

CandlesProvider = Callable[[str, Timeframe, datetime, int], List[Candle]]


class BaselineCorrelationService:
    MINIMUM_SAMPLE_COUNT = DEFAULT_MINIMUM_SAMPLE_COUNT

    def __init__(
        self,
        candles_provider: CandlesProvider,
        window_bars: int = DEFAULT_WINDOW_BARS,
        minimum_sample_count: int = DEFAULT_MINIMUM_SAMPLE_COUNT,
        max_staleness: timedelta = DEFAULT_MAX_STALENESS,
    ) -> None:
        self._candles_provider = candles_provider
        self._window_bars = window_bars
        self._minimum_sample_count = minimum_sample_count
        self._max_staleness = max_staleness

    def snapshot(self, symbol_a: str, symbol_b: str, timeframe: Timeframe, as_of_time: datetime) -> CorrelationSnapshot:
        base = dict(
            window_config_version=CORRELATION_WINDOW_VERSION, symbol_a=symbol_a, symbol_b=symbol_b,
            timeframe=timeframe.value, window_bars=self._window_bars,
        )

        candles_a = self._candles_provider(symbol_a, timeframe, as_of_time, self._window_bars)
        candles_b = self._candles_provider(symbol_b, timeframe, as_of_time, self._window_bars)

        if not candles_a or not candles_b:
            return CorrelationSnapshot(
                **base, sample_count=0, correlation=None, status="UNAVAILABLE",
                reason_codes=["NO_CANDLES_AVAILABLE"],
            )

        returns_a = _aligned_returns_by_timestamp(candles_a)
        returns_b = _aligned_returns_by_timestamp(candles_b)
        common_timestamps = sorted(set(returns_a) & set(returns_b))

        sample_count = len(common_timestamps)
        if sample_count < self._minimum_sample_count:
            return CorrelationSnapshot(
                **base, sample_count=sample_count, correlation=None, status="INSUFFICIENT_SAMPLE",
                reason_codes=[f"MIN_SAMPLE_NOT_MET:{sample_count}<{self._minimum_sample_count}"],
            )

        xs = [returns_a[t] for t in common_timestamps]
        ys = [returns_b[t] for t in common_timestamps]
        correlation = _pearson(xs, ys)

        latest_used = max(max(c.close_time for c in candles_a), max(c.close_time for c in candles_b))
        is_stale = (as_of_time - latest_used) > self._max_staleness
        status = "STALE" if is_stale else "OK"
        reason_codes = ["DATA_OLDER_THAN_MAX_STALENESS"] if is_stale else []

        return CorrelationSnapshot(
            **base, sample_count=sample_count,
            correlation=Decimal(str(round(correlation, 6))) if correlation is not None else None,
            computed_at=datetime.now(timezone.utc), is_stale=is_stale, status=status, reason_codes=reason_codes,
        )


def _aligned_returns_by_timestamp(candles: List[Candle]):
    sorted_candles = sorted(candles, key=lambda c: c.close_time)
    returns = {}
    for prev, cur in zip(sorted_candles, sorted_candles[1:], strict=False):
        if prev.close_price > 0:
            returns[cur.close_time] = float((cur.close_price - prev.close_price) / prev.close_price)
    return returns


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None  # e.g. zero variance in one series — genuinely undefined, not zero
