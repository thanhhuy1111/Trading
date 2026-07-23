"""Checksum helpers -- deliberately thin wrappers, not a second checksum scheme.

`checksum_candles` delegates to `packages.backtest.datasets.dataset_registry
.compute_dataset_checksum`, the SAME hashing scheme backtest sessions already use, so a
research dataset and a backtest dataset built from identical candles produce identical
checksums.
"""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, List

from packages.backtest.datasets import dataset_registry
from packages.market_data.models import Candle


def checksum_candles(candles: List[Candle]) -> str:
    return dataset_registry.compute_dataset_checksum(candles)


def checksum_json(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def checksum_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_code_commit() -> str:
    """Best-effort current git SHA for artifact lineage. Never raises -- artifact
    recording must not fail just because git metadata is unavailable (e.g. a source
    tarball with no .git directory)."""
    try:
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        sha = result.stdout.strip()
        return sha if result.returncode == 0 and sha else "unknown"
    except Exception:  # noqa: BLE001 - lineage metadata is best-effort, never fatal
        return "unknown"
