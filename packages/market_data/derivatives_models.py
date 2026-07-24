"""Futures/derivatives market data models (Multi-Agent Trading Advisor plan, Phase 1: Data
Foundation). Kept separate from `models.py`'s spot-market models since candles/order-book and
funding/open-interest/basis are conceptually distinct data types with different freshness and
availability characteristics -- see `packages/market_data/adapters/derivatives_base.py`.

Reuses `DataQualityStatus` (models.py) rather than inventing a parallel enum:
    HEALTHY  -> every sub-metric fetched successfully and within its freshness window.
    DEGRADED -> at least one sub-metric is missing/errored but at least one succeeded (a
                "PARTIAL" snapshot) -- never filled in with a fabricated value.
    STALE    -> every sub-metric that was fetched is older than its freshness window.
    UNHEALTHY -> every sub-metric failed -- no usable derivatives data at all.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import Field

from packages.market_data.models import BaseMarketDataModel


class DerivativesSnapshot(BaseMarketDataModel):
    """A point-in-time snapshot of Binance USDM perpetual futures metrics for one symbol.
    Each field is `Optional` and independently `None` when its underlying endpoint failed or
    returned nothing usable -- this class never substitutes a computed/estimated/last-known
    value for a field it could not fetch (Section 4.2 of the plan: "Agent không được tự tạo
    số liệu")."""

    mark_price: Optional[Decimal] = None
    index_price: Optional[Decimal] = None
    funding_rate: Optional[Decimal] = None
    next_funding_time: Optional[datetime] = None
    open_interest: Optional[Decimal] = None
    open_interest_change_pct: Optional[Decimal] = None
    long_short_account_ratio: Optional[Decimal] = None
    taker_buy_sell_ratio: Optional[Decimal] = None
    # Computed by the caller from (mark_price, a spot close price), never fetched directly --
    # see packages.market_data.derivatives_quality.compute_futures_basis_bps. None until that
    # computation has actually been performed with a real spot price.
    futures_basis_bps: Optional[Decimal] = None
    reason_codes: List[str] = Field(default_factory=list)


DEFAULT_FUNDING_INTERVAL_HOURS = 8
# How much staleness beyond the exchange's own funding interval before a fetched-but-old
# funding_rate is downgraded to STALE rather than trusted as HEALTHY. Kept generous (one full
# extra interval) since Binance's `premiumIndex` timestamp reflects the calculation time, not
# a hard SLA -- a tighter bound would flag normal operation as stale.
FUNDING_STALENESS_INTERVALS = 2
