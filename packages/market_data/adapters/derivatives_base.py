from decimal import Decimal
from typing import Any, Dict, Optional, Protocol

from packages.market_data.derivatives_models import DerivativesSnapshot


class DerivativesDataProvider(Protocol):
    """Read-only Async Interface for Futures/Derivatives Market Data Providers.

    CRITICAL: MUST NOT CONTAIN ANY ORDER PLACEMENT OR PRIVATE ACCOUNT METHODS -- mirrors the
    same safety rule as `packages.market_data.adapters.base.MarketDataProvider`. Kept as a
    separate Protocol from the spot `MarketDataProvider`, not a superset of it, since
    funding/open-interest/basis are conceptually distinct data types from candles/order-book
    (different freshness characteristics, different failure modes, and a symbol pair may have
    a spot market with no futures market or vice versa).

    Each `fetch_*` method returns `None` on failure (network error, symbol has no futures
    market, endpoint error) rather than raising -- callers assembling a full
    `DerivativesSnapshot` need to keep going and report a DEGRADED/PARTIAL snapshot when only
    some sub-metrics are available, never abort the whole snapshot for one failed sub-fetch.
    """

    async def fetch_snapshot(
        self, symbol: str, spot_reference_price: Optional[Decimal] = None,
    ) -> DerivativesSnapshot: ...

    async def fetch_mark_and_index_price(self, symbol: str) -> Optional[Dict[str, Any]]: ...

    async def fetch_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]: ...

    async def fetch_long_short_ratio(self, symbol: str) -> Optional[Dict[str, Any]]: ...

    async def fetch_taker_buy_sell_ratio(self, symbol: str) -> Optional[Dict[str, Any]]: ...
