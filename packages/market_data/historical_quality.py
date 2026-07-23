"""Historical dataset quality validation for offline research datasets (1h/4h/1d candle
series), distinct from packages/market_data/guardian.py's per-record streaming checks.

`data_guardian` validates one live record at a time (OHLC integrity, freshness, crossed
book). This module validates a whole historical *series*: duplicate timestamps, out-of-order
candles, missing candles (gaps against the expected interval), not-yet-closed candles, future
timestamps, and wrong interval spacing — the checks that only make sense with the full
sequence in hand, which is what a research dataset actually needs before any feature is
computed from it.

Nothing here forward-fills OHLC. A gap stays a gap; callers decide what to do with it via
`classify_gap_impact` / `filter_valid_decision_points`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple

from packages.market_data.models import Candle, Timeframe

# Expected wall-clock spacing between consecutive closed candles, per timeframe.
TIMEFRAME_INTERVAL: Dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
}


class DatasetQualityStatus(str, Enum):
    VALIDATED = "VALIDATED"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


@dataclass
class GapRecord:
    after_close_time: datetime   # last good candle before the gap
    before_close_time: datetime  # first good candle after the gap
    missing_count: int           # number of expected candles missing in between


@dataclass
class DatasetQualityReport:
    timeframe: Timeframe
    total_input_candles: int
    total_clean_candles: int
    duplicate_timestamps: int = 0
    out_of_order_count: int = 0
    invalid_ohlc_count: int = 0
    negative_volume_count: int = 0
    partial_candle_count: int = 0     # is_closed=False, or close_time in the future
    future_timestamp_count: int = 0
    wrong_spacing_count: int = 0      # consecutive-candle spacing not an exact interval multiple
    gaps: List[GapRecord] = field(default_factory=list)
    status: DatasetQualityStatus = DatasetQualityStatus.VALIDATED

    @property
    def missing_candle_count(self) -> int:
        return sum(g.missing_count for g in self.gaps)

    @property
    def raw_ingestion_status(self) -> str:
        """Reflects the RAW fetch, before cleaning: did the source return anything that had to
        be discarded (a still-forming boundary candle, an invalid row, a future timestamp)?
        A WARNING here is often expected and benign (see clean_dataset_status) — it just means
        "the ingestion process saw something worth noting", not "the resulting dataset is bad"."""
        if self.total_input_candles == 0:
            return "ERROR"
        defects = (
            self.partial_candle_count + self.future_timestamp_count
            + self.invalid_ohlc_count + self.negative_volume_count
        )
        return "WARNING" if defects > 0 else "OK"

    @property
    def clean_dataset_status(self) -> str:
        """Reflects only the CLEANED series that survives filtering — a forming boundary
        candle correctly stripped during ingestion must not, by itself, make this anything
        other than ACCEPTABLE. Mirrors `status` under friendlier names for this exact purpose."""
        return {
            DatasetQualityStatus.VALIDATED: "ACCEPTABLE",
            DatasetQualityStatus.DEGRADED: "DEGRADED",
            DatasetQualityStatus.REJECTED: "REJECTED",
        }[self.status]


# Severe-gap threshold: if missing candles exceed this fraction of the expected total for the
# segment, the whole segment is REJECTED rather than merely DEGRADED. Declared here (not
# tuned after looking at real data) per the same "no post-hoc gate loosening" principle
# already applied to the promotion gate.
SEVERE_GAP_FRACTION = Decimal("0.10")


def validate_historical_series(
    candles: List[Candle],
    timeframe: Timeframe,
    as_of: Optional[datetime] = None,
) -> Tuple[List[Candle], DatasetQualityReport]:
    """Returns (clean_candles, report). `clean_candles` is sorted, deduplicated, and excludes
    invalid-OHLC/negative-volume/partial/future-timestamp rows — everything the report counts
    as a defect is actually removed, not just flagged and left in."""
    as_of = as_of or datetime.now(timezone.utc)
    interval = TIMEFRAME_INTERVAL[timeframe]

    report = DatasetQualityReport(timeframe=timeframe, total_input_candles=len(candles), total_clean_candles=0)

    if not candles:
        report.status = DatasetQualityStatus.REJECTED
        return [], report

    sorted_candles = sorted(candles, key=lambda c: c.close_time)

    seen_close_times = set()
    clean: List[Candle] = []
    prev_close_time: Optional[datetime] = None

    for c in sorted_candles:
        if not c.is_closed:
            report.partial_candle_count += 1
            continue
        if c.close_time > as_of:
            report.future_timestamp_count += 1
            continue
        if c.open_price <= Decimal("0") or c.close_price <= Decimal("0") or c.low_price <= Decimal("0"):
            report.invalid_ohlc_count += 1
            continue
        if c.high_price < max(c.open_price, c.close_price, c.low_price):
            report.invalid_ohlc_count += 1
            continue
        if c.low_price > min(c.open_price, c.close_price, c.high_price):
            report.invalid_ohlc_count += 1
            continue
        if c.volume < Decimal("0"):
            report.negative_volume_count += 1
            continue
        if c.close_time in seen_close_times:
            report.duplicate_timestamps += 1
            continue
        if prev_close_time is not None and c.close_time < prev_close_time:
            # Already sorted, so this can only happen for a tie broken inconsistently; treat
            # as duplicate-class defect rather than silently reordering past it.
            report.out_of_order_count += 1
            continue

        seen_close_times.add(c.close_time)
        clean.append(c)
        prev_close_time = c.close_time

    # Interval spacing / gap detection over the CLEAN series only.
    for prev, cur in zip(clean, clean[1:], strict=False):
        spacing = cur.close_time - prev.close_time
        if spacing < interval:
            report.wrong_spacing_count += 1
            continue
        if spacing == interval:
            continue
        # spacing > interval: either an exact multiple (clean gap) or misaligned spacing.
        remainder = spacing % interval
        missing = int(spacing / interval) - 1
        if remainder != timedelta(0):
            report.wrong_spacing_count += 1
        if missing > 0:
            report.gaps.append(GapRecord(
                after_close_time=prev.close_time, before_close_time=cur.close_time, missing_count=missing,
            ))

    report.total_clean_candles = len(clean)

    expected_total = report.total_clean_candles + report.missing_candle_count
    severe = (
        expected_total > 0
        and (Decimal(report.missing_candle_count) / Decimal(expected_total)) > SEVERE_GAP_FRACTION
    )

    if severe or report.total_clean_candles == 0:
        report.status = DatasetQualityStatus.REJECTED
    elif report.gaps or report.duplicate_timestamps or report.out_of_order_count or report.wrong_spacing_count:
        report.status = DatasetQualityStatus.DEGRADED
    else:
        report.status = DatasetQualityStatus.VALIDATED

    return clean, report


def gap_overlaps_window(gaps: List[GapRecord], window_start: datetime, window_end: datetime) -> bool:
    """True if any gap falls at least partially inside [window_start, window_end]."""
    for g in gaps:
        if g.after_close_time < window_end and g.before_close_time > window_start:
            return True
    return False


@dataclass
class DecisionPointValidity:
    decision_timestamp: datetime
    valid: bool
    reason_codes: List[str] = field(default_factory=list)


def filter_valid_decision_points(
    decision_timestamps: List[datetime],
    gaps: List[GapRecord],
    feature_lookback: timedelta,
    label_horizon: timedelta,
) -> List[DecisionPointValidity]:
    """Gap policy (docs/research/DATA_QUALITY_POLICY.md §2.3):
      - a gap inside [t - feature_lookback, t] contaminates the features used to decide at t
        -> the decision point is invalid (GAP_IN_FEATURE_LOOKBACK).
      - a gap inside [t, t + label_horizon] contaminates the realized outcome used to label
        the decision made at t -> invalid (GAP_IN_LABEL_HORIZON).
      - a gap outside both windows doesn't affect this specific decision point at all.
    Small/harmless gaps are never silently ignored — they were already recorded in the
    DatasetQualityReport the caller got from validate_historical_series; this function only
    decides which *decision points* they invalidate.
    """
    results: List[DecisionPointValidity] = []
    for t in decision_timestamps:
        reasons: List[str] = []
        if gap_overlaps_window(gaps, t - feature_lookback, t):
            reasons.append("GAP_IN_FEATURE_LOOKBACK")
        if gap_overlaps_window(gaps, t, t + label_horizon):
            reasons.append("GAP_IN_LABEL_HORIZON")
        results.append(DecisionPointValidity(decision_timestamp=t, valid=(len(reasons) == 0), reason_codes=reasons))
    return results
