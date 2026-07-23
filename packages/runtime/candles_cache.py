"""Phase 8: offline, cache-only candles provider for the API layer's default recommendation
service wiring.

Reads whatever was already downloaded into `data/research/candles/<SYMBOL>_<TIMEFRAME>.json`
by `packages.research.data_fetcher` (Phase 0's real historical dataset). It never performs a
live network fetch itself — a missing cache file returns an empty candle list, which the
runtime already treats as `NO_CANDIDATE` / `NO_MARKET_DATA_AVAILABLE` (never an error, never a
network call from inside a request handler). This is what makes the API layer's default
wiring satisfy "no live exchange API" and "must run when the network is unavailable."
"""

from datetime import datetime
from typing import List

from packages.market_data.models import Candle, Timeframe
from packages.research.data_fetcher import _cache_path, _candle_from_json


def cached_candles_provider(symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> List[Candle]:
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return []
    import json

    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    candles = [_candle_from_json(row) for row in raw.get("candles", [])]
    return [c for c in candles if start <= c.close_time <= end]
