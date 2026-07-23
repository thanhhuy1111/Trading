"""Point-in-time feature table built by walking `FeaturePipeline.compute()` forward one
closed candle at a time -- the SAME feature engine the live paper-trading/backtest/
recommendation paths use, not a second implementation.

Point-in-time guarantee (belt and suspenders, two independent layers):
  1. This module only ever slices the candle history up to and including the candle being
     featured (`history[: i + 1]`) before calling `feature_pipeline.compute()` -- a candle
     with a later `open_time` is never even present in memory when a feature is computed.
  2. `FeaturePipeline.compute()` itself additionally filters to `close_time <= as_of_time`
     (packages/features/pipeline.py), so even a caller bug that passed extra future candles
     would not leak them into a feature value.

`test_feature_table_matches_direct_feature_pipeline_call` and
`test_feature_table_never_changes_when_future_candles_are_appended` in
tests/unit/test_research_features_labels.py are the leakage tests for this module.
"""

from typing import Dict, List, Tuple

import pandas as pd

from packages.features.models import FeatureComputationRequest
from packages.features.pipeline import feature_pipeline
from packages.market_data.models import Candle, Timeframe
from packages.research.config import FeatureConfig


def _group_by_symbol_timeframe(candles: List[Candle]) -> Dict[Tuple[str, str], List[Candle]]:
    groups: Dict[Tuple[str, str], List[Candle]] = {}
    for c in candles:
        tf_value = c.timeframe.value if hasattr(c.timeframe, "value") else str(c.timeframe)
        groups.setdefault((c.symbol, tf_value), []).append(c)
    for key in groups:
        groups[key] = sorted(groups[key], key=lambda c: c.open_time)
    return groups


def build_feature_table(
    candles: List[Candle],
    config: FeatureConfig,
    exchange: str = "binance",
) -> pd.DataFrame:
    """One row per (symbol, timeframe, open_time) with warmup_periods leading rows per
    group skipped (too little history for stable indicators). Missing individual feature
    values are zero-filled per `missing_value_policy`, with `had_missing_feature` recording
    which rows were affected -- never silently indistinguishable from a real zero.
    """
    groups = _group_by_symbol_timeframe(candles)
    rows = []

    for (symbol, tf_value), group_candles in groups.items():
        timeframe = Timeframe(tf_value)
        n = len(group_candles)
        if n <= config.warmup_periods:
            continue

        for i in range(config.warmup_periods, n):
            as_of_time = group_candles[i].close_time
            window_start = max(0, i + 1 - config.lookback_window)
            history_slice = group_candles[window_start : i + 1]

            request = FeatureComputationRequest(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                feature_set=config.version,
                as_of_time=as_of_time,
            )
            snapshot = feature_pipeline.compute(request, history_slice)

            had_missing = False
            row: Dict[str, object] = {
                "symbol": symbol,
                "timeframe": tf_value,
                "open_time": group_candles[i].open_time,
                "close_time": as_of_time,
                "reference_price": str(group_candles[i].close_price),
                "feature_snapshot_id": str(snapshot.snapshot_id),
                "quality_status": snapshot.quality_status.value,
            }
            for name in config.feature_names:
                raw = snapshot.values.get(name)
                if raw is None:
                    had_missing = True
                    row[f"feature__{name}"] = 0.0
                elif isinstance(raw, bool):
                    row[f"feature__{name}"] = 1.0 if raw else 0.0
                else:
                    row[f"feature__{name}"] = float(raw)
            row["had_missing_feature"] = had_missing
            rows.append(row)

    columns = (
        ["symbol", "timeframe", "open_time", "close_time", "reference_price", "feature_snapshot_id", "quality_status"]
        + [f"feature__{name}" for name in config.feature_names]
        + ["had_missing_feature"]
    )
    df = pd.DataFrame(rows, columns=columns)
    if not df.empty:
        df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    return df
