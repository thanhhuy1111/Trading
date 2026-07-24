"""Data-quality computation for `DerivativesSnapshot` (Multi-Agent Trading Advisor plan,
Phase 1). Kept as pure, network-free functions -- separate from the adapter itself -- so
quality logic is unit-testable without mocking HTTP (mirrors the split between
`packages.market_data.historical_quality` and the Binance spot adapter)."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from packages.market_data.derivatives_models import (
    DEFAULT_FUNDING_INTERVAL_HOURS,
    FUNDING_STALENESS_INTERVALS,
)
from packages.market_data.models import DataQualityStatus


def compute_futures_basis_bps(
    mark_price: Optional[Decimal], spot_reference_price: Optional[Decimal],
) -> Optional[Decimal]:
    """`(mark_price - spot_reference_price) / spot_reference_price * 10000`. Requires both a
    real futures mark price and a real spot reference price -- returns None (never a
    fabricated basis) if either is missing or the spot price is zero."""
    if mark_price is None or spot_reference_price is None or spot_reference_price == 0:
        return None
    return (mark_price - spot_reference_price) / spot_reference_price * Decimal("10000")


def compute_data_quality_status(
    fetch_succeeded: Dict[str, bool],
    as_of: Optional[datetime],
    now: datetime,
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> Tuple[DataQualityStatus, List[str]]:
    """`fetch_succeeded` maps each sub-metric name (e.g. "mark_and_index_price",
    "open_interest", "long_short_ratio", "taker_buy_sell_ratio") to whether its fetch
    succeeded. `as_of` is the freshest timestamp actually returned by a successful sub-fetch
    (None if every sub-fetch failed)."""
    reason_codes: List[str] = []
    succeeded = [name for name, ok in fetch_succeeded.items() if ok]
    failed = [name for name, ok in fetch_succeeded.items() if not ok]

    if not succeeded:
        reason_codes.append("ALL_DERIVATIVES_SUB_FETCHES_FAILED")
        return DataQualityStatus.UNHEALTHY, reason_codes

    if failed:
        reason_codes.append(f"PARTIAL_DATA_MISSING:{sorted(failed)}")

    if as_of is not None:
        staleness_threshold = timedelta(hours=funding_interval_hours * FUNDING_STALENESS_INTERVALS)
        if now - as_of > staleness_threshold:
            reason_codes.append("DERIVATIVES_DATA_STALE")
            return DataQualityStatus.STALE, reason_codes

    if failed:
        return DataQualityStatus.DEGRADED, reason_codes
    return DataQualityStatus.HEALTHY, reason_codes
