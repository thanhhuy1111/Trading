"""Checkpoint 2 opt-in live data acquisition: real 1h/4h candles for BTC/ETH/BNB/SOL,
validated through packages/market_data/historical_quality.py, with a real quality report
written out — not a synthetic/simulated run.

    python -m packages.research.fetch_timeframe_datasets
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from packages.market_data.historical_quality import validate_historical_series
from packages.market_data.models import Timeframe
from packages.research.data_fetcher import load_or_fetch_resumable

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "research" / "experiments" / "TIMEFRAME_DATA_QUALITY_REPORT.json"

SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
# Target coverage per the Checkpoint 2 plan: 1h >= 4 years if available, 4h >= 5 years if available.
TARGET_DAYS = {
    Timeframe.H1: 365 * 4 + 30,
    Timeframe.H4: 365 * 5 + 30,
}


def main() -> None:
    end = datetime.now(timezone.utc)
    results = []

    for timeframe, target_days in TARGET_DAYS.items():
        start = end - timedelta(days=target_days)
        for symbol in SYMBOLS:
            print(f"[fetch] {symbol} {timeframe.value} target {target_days}d ...")
            raw_candles = load_or_fetch_resumable(symbol, timeframe, start, end)
            clean, report = validate_historical_series(raw_candles, timeframe, as_of=end)

            coverage_days = (clean[-1].close_time - clean[0].close_time).days if clean else 0
            row = {
                "symbol": symbol,
                "timeframe": timeframe.value,
                "target_days": target_days,
                "raw_candle_count": len(raw_candles),
                "clean_candle_count": report.total_clean_candles,
                "coverage_days_achieved": coverage_days,
                "coverage_target_met": coverage_days >= target_days - 30,  # small tolerance
                "duplicate_timestamps": report.duplicate_timestamps,
                "out_of_order_count": report.out_of_order_count,
                "invalid_ohlc_count": report.invalid_ohlc_count,
                "negative_volume_count": report.negative_volume_count,
                "partial_candle_count": report.partial_candle_count,
                "future_timestamp_count": report.future_timestamp_count,
                "wrong_spacing_count": report.wrong_spacing_count,
                "gap_count": len(report.gaps),
                "missing_candle_count": report.missing_candle_count,
                "quality_status": report.status.value,
                "range_start": clean[0].close_time.isoformat() if clean else None,
                "range_end": clean[-1].close_time.isoformat() if clean else None,
            }
            results.append(row)
            print(
                f"[fetch] {symbol} {timeframe.value}: {row['clean_candle_count']} clean candles, "
                f"{row['coverage_days_achieved']}d coverage, status={row['quality_status']}, "
                f"gaps={row['gap_count']} ({row['missing_candle_count']} candles missing)"
            )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}
    with open(OUTPUT_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[fetch] wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
