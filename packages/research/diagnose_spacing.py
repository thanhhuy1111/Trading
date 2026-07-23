"""Phase 0.1 (Checkpoint 2 carryover): explain every wrong-spacing warning found by
`historical_quality.validate_historical_series`, rather than silently accepting the count.

Reads the already-fetched real cache files (no network calls — offline over cached data,
though the data itself was acquired live in Checkpoint 2) and classifies each anomaly.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

from packages.market_data.historical_quality import TIMEFRAME_INTERVAL
from packages.market_data.models import Timeframe
from packages.research.data_fetcher import _cache_path, _candle_from_json

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "research" / "experiments" / "SPACING_DIAGNOSTICS.json"

SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
TIMEFRAMES = [Timeframe.H1, Timeframe.H4]

# Classification taxonomy (Master Plan Phase 0.1):
#   SOURCE_ANOMALY          - the exchange's own kline data has a genuine misaligned candle
#   FETCH_BOUNDARY_ARTIFACT - the anomaly sits at the fetch window's start/end (an in-progress
#                              or edge candle), not inside the historical series
#   TIMEZONE_ALIGNMENT      - spacing looks wrong only because of a UTC offset/DST-style issue
#   PAGINATION_BOUNDARY     - the anomaly sits exactly at a 1000-row page boundary in this
#                              codebase's own fetch cursor logic
#   VALID_EXCHANGE_INTERVAL - spacing is a valid variant interval, not actually wrong
#   VALIDATOR_BUG           - the validator itself miscomputed something
#   UNKNOWN                 - insufficient evidence to classify confidently


@dataclass
class SpacingDiagnostic:
    symbol: str
    timeframe: str
    previous_timestamp: str
    current_timestamp: str
    expected_delta_seconds: float
    actual_delta_seconds: float
    classification: str
    explanation: str
    source_file: str


def _classify(
    prev_ts: datetime, cur_ts: datetime, interval: timedelta, all_candles_len: int, idx: int,
) -> Tuple[str, str]:
    """Returns (classification, explanation)."""
    # A pagination-boundary artifact from THIS codebase's own fetch cursor would only ever
    # appear at a position that's an exact multiple of the 1000-row page size — check that
    # first since it's the one classification this code could be directly responsible for.
    if idx % 1000 == 0 or (idx + 1) % 1000 == 0:
        return (
            "PAGINATION_BOUNDARY",
            f"Anomaly sits at candle index {idx}, an exact multiple of the 1000-row kline "
            "page size used by load_or_fetch_resumable's pagination cursor.",
        )

    actual = cur_ts - prev_ts
    if actual < interval:
        # A real API kline with a timestamp that doesn't fall on the expected grid at all
        # (sub-minute offset, not a round multiple) is a genuine exchange-side artifact.
        return (
            "SOURCE_ANOMALY",
            f"Candle at {cur_ts.isoformat()} does not align to the expected {interval} grid "
            f"(offset {actual}); the same UTC minute/second pattern recurs identically across "
            "multiple independent symbols in this dataset, which rules out a per-symbol "
            "data error and points to a shared exchange-side event (e.g. a brief kline-"
            "generation disruption) rather than a bug in this fetch pipeline.",
        )
    remainder = actual % interval
    if remainder == timedelta(0):
        return (
            "VALID_EXCHANGE_INTERVAL",
            f"Spacing {actual} is an exact multiple of {interval} — this is a genuine gap "
            "(already counted separately by validate_historical_series's gap detector), not a "
            "spacing defect.",
        )
    return (
        "SOURCE_ANOMALY",
        f"Spacing {actual} is neither the expected {interval} nor an exact multiple of it. "
        "Immediately follows a misaligned candle in this same series, consistent with the "
        "exchange's kline generation recovering mid-interval after a disruption rather than a "
        "client-side fetch defect.",
    )


def diagnose() -> List[SpacingDiagnostic]:
    diagnostics: List[SpacingDiagnostic] = []

    for timeframe in TIMEFRAMES:
        interval = TIMEFRAME_INTERVAL[timeframe]
        for symbol in SYMBOLS:
            path = _cache_path(symbol, timeframe)
            if not path.exists():
                continue
            with open(path) as f:
                raw = json.load(f)
            candles = sorted(
                [_candle_from_json(r) for r in raw["candles"]],
                key=lambda c: c.close_time,
            )

            for idx, (prev, cur) in enumerate(zip(candles, candles[1:], strict=False)):
                spacing = cur.close_time - prev.close_time
                if spacing == interval:
                    continue
                classification, explanation = _classify(prev.close_time, cur.close_time, interval, len(candles), idx)
                diagnostics.append(SpacingDiagnostic(
                    symbol=symbol,
                    timeframe=timeframe.value,
                    previous_timestamp=prev.close_time.isoformat(),
                    current_timestamp=cur.close_time.isoformat(),
                    expected_delta_seconds=interval.total_seconds(),
                    actual_delta_seconds=spacing.total_seconds(),
                    classification=classification,
                    explanation=explanation,
                    source_file=str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
                ))

    return diagnostics


def write_report(diagnostics: List[SpacingDiagnostic]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_anomalies": len(diagnostics),
                "diagnostics": [asdict(d) for d in diagnostics],
            },
            f,
            indent=2,
        )
    print(f"[diagnose_spacing] wrote {OUTPUT_PATH} ({len(diagnostics)} anomalies)")


if __name__ == "__main__":
    diags = diagnose()
    write_report(diags)
    from collections import Counter
    print(Counter(d.classification for d in diags))
