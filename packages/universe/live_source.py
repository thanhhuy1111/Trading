"""Live (network-touching) metadata fetch for universe selection.

This is the ONLY module in packages/universe that calls the network, and it is only ever
invoked explicitly (`python -m packages.universe.build_snapshot` or a caller that opts in) —
never by the default offline test suite. Uses the same public Binance data mirror as
packages/research/data_fetcher.py (api.binance.com is geo-blocked in this environment;
data-api.binance.vision serves the identical public REST contract).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List

import httpx

from packages.common.logger import logger
from packages.universe.models import SymbolMetadata

DATA_MIRROR_BASE_URL = "https://data-api.binance.vision"

SEED_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT",
]


def _to_canonical(exchange_symbol: str, quote_asset: str) -> str:
    base = exchange_symbol[: -len(quote_asset)] if exchange_symbol.endswith(quote_asset) else exchange_symbol
    return f"{base}/{quote_asset}"


def _fetch_history_days_available(client: httpx.Client, exchange_symbol: str) -> int:
    resp = client.get(
        f"{DATA_MIRROR_BASE_URL}/api/v3/klines",
        params={"symbol": exchange_symbol, "interval": "1d", "startTime": 0, "limit": 1},
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return 0
    first_open_ms = rows[0][0]
    first_open = datetime.fromtimestamp(first_open_ms / 1000.0, tz=timezone.utc)
    return (datetime.now(timezone.utc) - first_open).days


def _fetch_recent_completeness_pct(client: httpx.Client, exchange_symbol: str, window_days: int) -> Decimal:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=window_days)
    resp = client.get(
        f"{DATA_MIRROR_BASE_URL}/api/v3/klines",
        params={
            "symbol": exchange_symbol, "interval": "1d",
            "startTime": int(start.timestamp() * 1000), "endTime": int(end.timestamp() * 1000),
            "limit": window_days + 5,
        },
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return Decimal("0")
    close_times = [r[6] for r in rows]
    duplicates = len(close_times) - len(set(close_times))
    # Expect ~1 row/day; completeness = actual distinct rows / expected days, capped at 100%.
    completeness = (Decimal(len(set(close_times))) / Decimal(window_days)) * Decimal("100")
    if duplicates > 0:
        logger.warning(
            "Duplicate candles detected in completeness check",
            extra={"symbol": exchange_symbol, "duplicates": duplicates},
        )
    return min(completeness, Decimal("100"))


def fetch_universe_metadata(exchange_symbols: List[str] = None) -> List[SymbolMetadata]:
    exchange_symbols = exchange_symbols or SEED_UNIVERSE
    results: List[SymbolMetadata] = []

    with httpx.Client(timeout=20.0, headers={"User-Agent": "AlphaResearchCampaign/1.0"}) as client:
        info_resp = client.get(
            f"{DATA_MIRROR_BASE_URL}/api/v3/exchangeInfo",
            params={"symbols": "[" + ",".join(f'"{s}"' for s in exchange_symbols) + "]"},
        )
        info_resp.raise_for_status()
        info_by_symbol = {s["symbol"]: s for s in info_resp.json()["symbols"]}

        ticker_resp = client.get(
            f"{DATA_MIRROR_BASE_URL}/api/v3/ticker/24hr",
            params={"symbols": "[" + ",".join(f'"{s}"' for s in exchange_symbols) + "]"},
        )
        ticker_resp.raise_for_status()
        ticker_by_symbol = {t["symbol"]: t for t in ticker_resp.json()}

        for exch_symbol in exchange_symbols:
            info = info_by_symbol.get(exch_symbol)
            ticker = ticker_by_symbol.get(exch_symbol)
            if info is None:
                results.append(SymbolMetadata(
                    symbol=exch_symbol, exchange_symbol=exch_symbol, base_asset="UNKNOWN",
                    quote_asset="UNKNOWN", status="UNKNOWN", is_spot_trading_allowed=False,
                    metadata_available=False,
                ))
                continue

            base_asset = info["baseAsset"]
            quote_asset = info["quoteAsset"]
            canonical = _to_canonical(exch_symbol, quote_asset)

            try:
                history_days = _fetch_history_days_available(client, exch_symbol)
                completeness = _fetch_recent_completeness_pct(client, exch_symbol, window_days=30)
            except Exception as exc:  # noqa: BLE001 - a data-fetch failure must not crash the whole snapshot
                logger.error("Universe metadata fetch failed", extra={"symbol": exch_symbol, "error": str(exc)})
                history_days = None
                completeness = None

            results.append(SymbolMetadata(
                symbol=canonical,
                exchange_symbol=exch_symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                status=info["status"],
                is_spot_trading_allowed=info.get("isSpotTradingAllowed", False),
                history_days_available=history_days,
                quote_volume_24h_usdt=Decimal(ticker["quoteVolume"]) if ticker else None,
                recent_candle_completeness_pct=completeness,
                best_bid=Decimal(ticker["bidPrice"]) if ticker and ticker.get("bidPrice") else None,
                best_ask=Decimal(ticker["askPrice"]) if ticker and ticker.get("askPrice") else None,
                metadata_available=True,
            ))

    return results
