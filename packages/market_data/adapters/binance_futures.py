import asyncio
import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from packages.common.logger import logger
from packages.market_data.derivatives_models import DerivativesSnapshot
from packages.market_data.derivatives_quality import compute_data_quality_status, compute_futures_basis_bps
from packages.market_data.symbol_registry import symbol_registry


def _get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class BinancePublicFuturesDataProvider:
    """Read-Only Public Binance USDM Futures Data Provider.

    CRITICAL SAFETY RULES (mirrors `BinancePublicMarketDataProvider`):
    1. Uses PUBLIC API endpoints ONLY (fapi.binance.com).
    2. NO trading API keys or private user streams.
    3. NO order placement, leverage, or margin-mode methods exist on this class.

    Every `fetch_*` sub-method returns `None` on any failure (network error, symbol has no
    USDM futures market, malformed response) rather than raising -- `fetch_snapshot` gathers
    all of them and reports an honest PARTIAL/DEGRADED result when only some succeed, never a
    fabricated value for the ones that failed.
    """

    REST_BASE_URL = "https://fapi.binance.com"
    DEFAULT_TIMEOUT_SECONDS = 10.0

    def __init__(self, exchange_id: str = "binance_usdm_futures", timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self.exchange_id = exchange_id
        self._timeout_seconds = timeout_seconds

    async def _get_json(self, path: str, params: Dict[str, str]) -> Any:
        query = urllib.parse.urlencode(params)
        url = f"{self.REST_BASE_URL}{path}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradingBot/1.0"})
        loop = asyncio.get_running_loop()
        resp_data = await loop.run_in_executor(
            None,
            lambda: urllib.request.urlopen(req, timeout=self._timeout_seconds, context=_get_ssl_context()).read(),
        )
        return json.loads(resp_data.decode("utf-8"))

    async def fetch_mark_and_index_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """GET /fapi/v1/premiumIndex -- mark price, index price, last funding rate, next
        funding time. Public endpoint, no API key."""
        exch_symbol = symbol_registry.to_exchange_symbol(symbol)
        try:
            raw = await self._get_json("/fapi/v1/premiumIndex", {"symbol": exch_symbol})
            return {
                "mark_price": Decimal(str(raw["markPrice"])),
                "index_price": Decimal(str(raw["indexPrice"])),
                "funding_rate": Decimal(str(raw["lastFundingRate"])),
                "next_funding_time": datetime.fromtimestamp(int(raw["nextFundingTime"]) / 1000.0, tz=timezone.utc),
                "as_of": datetime.fromtimestamp(int(raw["time"]) / 1000.0, tz=timezone.utc),
            }
        except Exception as e:  # noqa: BLE001 - degrades to None, caller decides PARTIAL/UNAVAILABLE
            logger.error("Binance futures fetch_mark_and_index_price error", extra={"symbol": symbol, "error": str(e)})
            return None

    async def fetch_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """GET /fapi/v1/openInterest -- current open interest (in base-asset units)."""
        exch_symbol = symbol_registry.to_exchange_symbol(symbol)
        try:
            raw = await self._get_json("/fapi/v1/openInterest", {"symbol": exch_symbol})
            return {
                "open_interest": Decimal(str(raw["openInterest"])),
                "as_of": datetime.fromtimestamp(int(raw["time"]) / 1000.0, tz=timezone.utc),
            }
        except Exception as e:  # noqa: BLE001
            logger.error("Binance futures fetch_open_interest error", extra={"symbol": symbol, "error": str(e)})
            return None

    async def fetch_long_short_ratio(self, symbol: str, period: str = "5m") -> Optional[Dict[str, Any]]:
        """GET /futures/data/globalLongShortAccountRatio -- most recent global long/short
        account ratio."""
        exch_symbol = symbol_registry.to_exchange_symbol(symbol)
        try:
            raw = await self._get_json(
                "/futures/data/globalLongShortAccountRatio", {"symbol": exch_symbol, "period": period, "limit": "1"},
            )
            if not raw:
                return None
            latest = raw[0]
            return {
                "long_short_account_ratio": Decimal(str(latest["longShortRatio"])),
                "as_of": datetime.fromtimestamp(int(latest["timestamp"]) / 1000.0, tz=timezone.utc),
            }
        except Exception as e:  # noqa: BLE001
            logger.error("Binance futures fetch_long_short_ratio error", extra={"symbol": symbol, "error": str(e)})
            return None

    async def fetch_taker_buy_sell_ratio(self, symbol: str, period: str = "5m") -> Optional[Dict[str, Any]]:
        """GET /futures/data/takerlongshortRatio -- most recent taker buy/sell volume
        ratio."""
        exch_symbol = symbol_registry.to_exchange_symbol(symbol)
        try:
            raw = await self._get_json(
                "/futures/data/takerlongshortRatio", {"symbol": exch_symbol, "period": period, "limit": "1"},
            )
            if not raw:
                return None
            latest = raw[0]
            return {
                "taker_buy_sell_ratio": Decimal(str(latest["buySellRatio"])),
                "as_of": datetime.fromtimestamp(int(latest["timestamp"]) / 1000.0, tz=timezone.utc),
            }
        except Exception as e:  # noqa: BLE001
            logger.error("Binance futures fetch_taker_buy_sell_ratio error", extra={"symbol": symbol, "error": str(e)})
            return None

    async def fetch_snapshot(self, symbol: str, spot_reference_price: Optional[Decimal] = None) -> DerivativesSnapshot:
        """Gathers all sub-metrics concurrently and assembles one `DerivativesSnapshot`.
        `open_interest_change_pct` is intentionally left `None` in this phase -- computing it
        requires a historical open-interest series, which is out of scope until this data is
        persisted (see docs on the deferred `derivatives_metrics` table). `futures_basis_bps`
        is only computed when the caller supplies a real `spot_reference_price` -- this
        adapter never fetches spot data itself, keeping the spot/futures Protocols decoupled.
        """
        mark_index, open_interest, long_short, taker_ratio = await asyncio.gather(
            self.fetch_mark_and_index_price(symbol),
            self.fetch_open_interest(symbol),
            self.fetch_long_short_ratio(symbol),
            self.fetch_taker_buy_sell_ratio(symbol),
        )

        fetch_succeeded = {
            "mark_and_index_price": mark_index is not None,
            "open_interest": open_interest is not None,
            "long_short_ratio": long_short is not None,
            "taker_buy_sell_ratio": taker_ratio is not None,
        }
        as_of_candidates = [
            d["as_of"] for d in (mark_index, open_interest, long_short, taker_ratio) if d is not None
        ]
        freshest_as_of = max(as_of_candidates) if as_of_candidates else None
        now = datetime.now(timezone.utc)
        status, reason_codes = compute_data_quality_status(fetch_succeeded, freshest_as_of, now)

        mark_price = mark_index["mark_price"] if mark_index else None
        return DerivativesSnapshot(
            exchange=self.exchange_id,
            symbol=symbol,
            exchange_timestamp=freshest_as_of or now,
            source="binance_public",
            data_quality_status=status,
            mark_price=mark_price,
            index_price=mark_index["index_price"] if mark_index else None,
            funding_rate=mark_index["funding_rate"] if mark_index else None,
            next_funding_time=mark_index["next_funding_time"] if mark_index else None,
            open_interest=open_interest["open_interest"] if open_interest else None,
            open_interest_change_pct=None,
            long_short_account_ratio=long_short["long_short_account_ratio"] if long_short else None,
            taker_buy_sell_ratio=taker_ratio["taker_buy_sell_ratio"] if taker_ratio else None,
            futures_basis_bps=compute_futures_basis_bps(mark_price, spot_reference_price),
            reason_codes=reason_codes,
        )
