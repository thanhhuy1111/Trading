"""Append-only local history cache for `DerivativesSnapshot`s (Multi-Agent Trading Advisor
plan, Phase 2: derivatives feature pipeline).

Binance's `/futures/data/*` endpoints (open interest history, long/short ratio, taker
buy/sell ratio) don't support arbitrary bulk backfill the way spot klines do -- there is
nothing to backfill from. Historical derivatives data can only be accumulated forward, one
real poll at a time, so this module is deliberately a simple append-only cache (mirroring
`packages.research.data_fetcher`'s candle-cache pattern, but without that module's pagination/
resume logic, which has no equivalent here) rather than a bulk-fetch-and-store pipeline.

Cached under `data/research/derivatives/` -- `data/` is fully gitignored, matching the
existing candle cache's convention (regenerable, never committed).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from packages.market_data.derivatives_models import DerivativesSnapshot

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "research" / "derivatives"
MIN_APPEND_INTERVAL_MINUTES = 5  # matches Binance's own period=5m granularity on ratio endpoints
RETENTION_DAYS = 30


def _cache_path(symbol: str, cache_dir: Path) -> Path:
    safe_symbol = symbol.replace("/", "")
    return cache_dir / f"{safe_symbol}.json"


def _read_all(symbol: str, cache_dir: Path) -> List[DerivativesSnapshot]:
    path = _cache_path(symbol, cache_dir)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    snapshots = []
    for item in raw.get("snapshots", []):
        try:
            snapshots.append(DerivativesSnapshot.model_validate(item))
        except Exception:  # noqa: BLE001 - one malformed cached entry never blocks the rest
            continue
    return snapshots


def _write_all(symbol: str, snapshots: List[DerivativesSnapshot], cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(symbol, cache_dir)
    payload = {
        "symbol": symbol,
        "snapshot_count": len(snapshots),
        "snapshots": [s.model_dump(mode="json") for s in snapshots],
    }
    path.write_text(json.dumps(payload))


def append_snapshot(
    snapshot: DerivativesSnapshot, cache_dir: Path = DEFAULT_CACHE_DIR,
) -> bool:
    """Appends `snapshot` to the symbol's history file if enough time has passed since the
    newest cached entry (`MIN_APPEND_INTERVAL_MINUTES`) -- never appends a near-duplicate of
    the last real poll. Also trims entries older than `RETENTION_DAYS` on every write, so the
    file is self-bounding. Returns True if the snapshot was actually appended, False if it was
    skipped (too soon after the last entry)."""
    existing = _read_all(snapshot.symbol, cache_dir)
    existing.sort(key=lambda s: s.exchange_timestamp)

    if existing:
        newest = existing[-1]
        if snapshot.exchange_timestamp - newest.exchange_timestamp < timedelta(minutes=MIN_APPEND_INTERVAL_MINUTES):
            return False

    cutoff = snapshot.exchange_timestamp - timedelta(days=RETENTION_DAYS)
    retained = [s for s in existing if s.exchange_timestamp >= cutoff]
    retained.append(snapshot)
    _write_all(snapshot.symbol, retained, cache_dir)
    return True


def load_history(
    symbol: str,
    as_of: datetime,
    lookback: Optional[timedelta] = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> List[DerivativesSnapshot]:
    """Returns cached snapshots for `symbol` with `exchange_timestamp <= as_of` (never leaks a
    snapshot from after the requested point in time into a historical read), optionally further
    restricted to the trailing `lookback` window, sorted ascending by timestamp."""
    snapshots = _read_all(symbol, cache_dir)
    snapshots = [s for s in snapshots if s.exchange_timestamp <= as_of]
    if lookback is not None:
        cutoff = as_of - lookback
        snapshots = [s for s in snapshots if s.exchange_timestamp >= cutoff]
    snapshots.sort(key=lambda s: s.exchange_timestamp)
    return snapshots
