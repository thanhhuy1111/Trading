"""Real multi-year historical OHLCV acquisition for the Alpha Research Campaign.

Pulls actual public Binance kline data (no synthetic/fabricated bars) via Binance's public
market-data mirror `data-api.binance.vision`. This mirror serves the exact same
`/api/v3/klines` contract as `api.binance.com` (verified against `packages/market_data/
adapters/binance.py`'s parsing) but is reachable from this environment, whereas
`api.binance.com` returns HTTP 451 (geo-restricted) here. No trading endpoints, no API key,
read-only historical candles only.

Fetched candles are cached to `data/research/candles/` (gitignored — regenerable, not
committed) as the canonical local source for the research campaign's dataset registration.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import List

import httpx

from packages.common.logger import logger
from packages.market_data.models import Candle, Timeframe

DATA_MIRROR_BASE_URL = "https://data-api.binance.vision"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "research" / "candles"

TIMEFRAME_MAP = {
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
}

_KLINES_LIMIT = 1000  # Binance REST API max rows per request


def _cache_path(symbol: str, timeframe: Timeframe) -> Path:
    safe_symbol = symbol.replace("/", "")
    return CACHE_DIR / f"{safe_symbol}_{timeframe.value}.json"


def _parse_kline_row(item: list, exchange_id: str, symbol: str, timeframe: Timeframe) -> Candle:
    open_ts = datetime.fromtimestamp(item[0] / 1000.0, tz=timezone.utc)
    close_ts = datetime.fromtimestamp(item[6] / 1000.0, tz=timezone.utc)
    return Candle(
        exchange=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_ts,
        close_time=close_ts,
        open_price=Decimal(str(item[1])),
        high_price=Decimal(str(item[2])),
        low_price=Decimal(str(item[3])),
        close_price=Decimal(str(item[4])),
        volume=Decimal(str(item[5])),
        quote_volume=Decimal(str(item[7])),
        trades_count=int(item[8]),
        exchange_timestamp=close_ts,
        is_closed=True,
    )


def fetch_symbol_history(
    symbol: str,
    timeframe: Timeframe,
    start_time: datetime,
    end_time: datetime,
    exchange_id: str = "binance",
    request_pause_seconds: float = 0.2,
) -> List[Candle]:
    """Paginates real klines for [start_time, end_time] from the public Binance data mirror."""
    exch_symbol = symbol.replace("/", "")
    tf_str = TIMEFRAME_MAP[timeframe]

    candles: List[Candle] = []
    cursor_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    with httpx.Client(timeout=20.0, headers={"User-Agent": "AlphaResearchCampaign/1.0"}) as client:
        while cursor_ms < end_ms:
            resp = client.get(
                f"{DATA_MIRROR_BASE_URL}/api/v3/klines",
                params={
                    "symbol": exch_symbol,
                    "interval": tf_str,
                    "startTime": cursor_ms,
                    "endTime": end_ms,
                    "limit": _KLINES_LIMIT,
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                break

            for item in rows:
                candles.append(_parse_kline_row(item, exchange_id, symbol, timeframe))

            last_close_ms = rows[-1][6]
            next_cursor_ms = last_close_ms + 1
            if next_cursor_ms <= cursor_ms:
                break  # safety against non-advancing pagination
            cursor_ms = next_cursor_ms

            if len(rows) < _KLINES_LIMIT:
                break  # reached the end of available data

            time.sleep(request_pause_seconds)  # be a polite citizen of a public mirror

    logger.info(
        "Fetched real historical candles",
        extra={"symbol": symbol, "timeframe": timeframe.value, "candle_count": len(candles)},
    )
    return candles


def _candle_to_json(c: Candle) -> dict:
    return {
        "exchange": c.exchange,
        "symbol": c.symbol,
        "timeframe": c.timeframe.value,
        "open_time": c.open_time.isoformat(),
        "close_time": c.close_time.isoformat(),
        "open_price": str(c.open_price),
        "high_price": str(c.high_price),
        "low_price": str(c.low_price),
        "close_price": str(c.close_price),
        "volume": str(c.volume),
        "quote_volume": str(c.quote_volume),
        "trades_count": c.trades_count,
    }


def _candle_from_json(d: dict) -> Candle:
    close_ts = datetime.fromisoformat(d["close_time"])
    return Candle(
        exchange=d["exchange"],
        symbol=d["symbol"],
        timeframe=Timeframe(d["timeframe"]),
        open_time=datetime.fromisoformat(d["open_time"]),
        close_time=close_ts,
        open_price=Decimal(d["open_price"]),
        high_price=Decimal(d["high_price"]),
        low_price=Decimal(d["low_price"]),
        close_price=Decimal(d["close_price"]),
        volume=Decimal(d["volume"]),
        quote_volume=Decimal(d["quote_volume"]),
        trades_count=d["trades_count"],
        exchange_timestamp=close_ts,
        is_closed=True,
    )


def load_or_fetch(
    symbol: str,
    timeframe: Timeframe,
    start_time: datetime,
    end_time: datetime,
    force_refresh: bool = False,
) -> List[Candle]:
    """Returns a locally cached real candle series, fetching from the public mirror on a
    cache miss. The cache is content-addressed only by (symbol, timeframe) — callers that
    need a specific date range slice the returned list themselves."""
    path = _cache_path(symbol, timeframe)
    if path.exists() and not force_refresh:
        with open(path) as f:
            raw = json.load(f)
        candles = [_candle_from_json(row) for row in raw["candles"]]
        logger.info(
            "Loaded cached real historical candles",
            extra={"symbol": symbol, "timeframe": timeframe.value, "candle_count": len(candles), "cache_path": str(path)},
        )
        return candles

    candles = fetch_symbol_history(symbol, timeframe, start_time, end_time)
    if not candles:
        raise RuntimeError(f"NO_DATA_FETCHED: {symbol} {timeframe.value} returned zero real candles")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "symbol": symbol,
                "timeframe": timeframe.value,
                "source": f"{DATA_MIRROR_BASE_URL}/api/v3/klines",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "candle_count": len(candles),
                "candles": [_candle_to_json(c) for c in candles],
            },
            f,
        )
    return candles


if __name__ == "__main__":
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * 7 + 200)  # multi-year: ~7+ years of daily bars
    for sym in ["BTC/USDT", "ETH/USDT"]:
        c = load_or_fetch(sym, Timeframe.D1, start, end, force_refresh=True)
        print(f"{sym}: {len(c)} real daily candles, {c[0].close_time.date()} -> {c[-1].close_time.date()}")
