"""Cost-aware triple-barrier labeling.

For every (symbol, timeframe, entry candle, horizon) this walks FORWARD through
already-known historical candles to find whichever of three barriers is touched first:

    upper_barrier   entry_reference_price * (1 + upper_barrier_pct)   -> "UPPER"
    lower_barrier   entry_reference_price * (1 - lower_barrier_pct)   -> "LOWER"
    time_barrier    entry_time + horizon_minutes                       -> "TIME"

This is the ONE place in the pipeline that is allowed to look forward -- that is what a
label is. Features (packages.research.feature_dataset) never call into this module and
never receive its output; the anti-leakage tests in
tests/unit/test_research_features_labels.py assert the feature table can be built with
zero rows from this module in scope, and that appending future candles never changes a
feature already computed at an earlier as_of_time.

Costs are estimated via the EXISTING `packages.governance.cost_estimator.cost_estimator`
-- the same conservative fee+spread+slippage+uncertainty-buffer model the live
paper-trading path and packages.recommendation.cost_service both use.

Label semantics (long-only, spot):
    first_barrier_hit == "LOWER"           -> label = "LOSS"
    first_barrier_hit == "UPPER"           -> label = "PROFIT" if net_return_bps > 0 else "LOSS"
                                               (an upper-barrier touch can still be a net
                                               loss once costs are subtracted for a small
                                               barrier distance -- this is intentional and
                                               is exactly why costs are deducted BEFORE
                                               labeling, not after)
    first_barrier_hit == "TIME"            -> label = "TIMEOUT" (regardless of sign -- a
                                               timeout is a distinct outcome class from a
                                               barrier touch, per the triple-barrier method)

If both barriers would be touched within the SAME forward candle (i.e. its high >= upper
AND low <= lower), the LOWER barrier is assumed hit first (conservative: a strategy cannot
know intrabar path from OHLC alone, and assuming the favorable outcome would bias results).
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import pandas as pd

from packages.governance.cost_estimator import cost_estimator
from packages.market_data.models import Candle
from packages.research.config import LabelConfig

BPS = Decimal("10000")


def _first_barrier_hit(
    entry_reference_price: Decimal,
    upper_barrier: Decimal,
    lower_barrier: Decimal,
    time_barrier: "pd.Timestamp",
    forward_candles: List[Candle],
) -> Tuple[Optional[str], Optional[Decimal], Optional[datetime]]:
    """Returns (first_barrier_hit, exit_price, label_end_time)."""
    for c in forward_candles:
        if c.close_time > time_barrier:
            break
        touched_upper = c.high_price >= upper_barrier
        touched_lower = c.low_price <= lower_barrier
        if touched_lower:
            return "LOWER", lower_barrier, c.close_time
        if touched_upper:
            return "UPPER", upper_barrier, c.close_time

    # No barrier touched within the horizon: TIMEOUT, exit at the last candle at/under
    # the time barrier, or the reference price itself if no forward candle exists yet.
    candles_in_window = [c for c in forward_candles if c.close_time <= time_barrier]
    if candles_in_window:
        last = candles_in_window[-1]
        return "TIME", last.close_price, last.close_time
    return None, None, None


def build_label_table(
    candles: List[Candle],
    config: LabelConfig,
) -> pd.DataFrame:
    """One row per (symbol, timeframe, entry open_time, horizon_minutes). Entries too
    close to the end of the available candle history to reach their horizon are skipped
    entirely (never partially labeled).
    """
    groups: Dict[Tuple[str, str], List[Candle]] = {}
    for c in candles:
        tf_value = c.timeframe.value if hasattr(c.timeframe, "value") else str(c.timeframe)
        groups.setdefault((c.symbol, tf_value), []).append(c)
    for key in groups:
        groups[key] = sorted(groups[key], key=lambda c: c.open_time)

    rows = []
    for (symbol, tf_value), group_candles in groups.items():
        cost = cost_estimator.estimate_cost(symbol) if config.use_cost_estimator else None
        cost_bps = cost.total_cost_bps if cost is not None else Decimal("0.0")

        n = len(group_candles)
        for i in range(n):
            entry_candle = group_candles[i]
            entry_time = entry_candle.close_time
            entry_reference_price = entry_candle.close_price
            upper_barrier = entry_reference_price * (Decimal("1") + config.upper_barrier_pct)
            lower_barrier = entry_reference_price * (Decimal("1") - config.lower_barrier_pct)

            for horizon_minutes in config.horizons_minutes:
                time_barrier = entry_time + timedelta(minutes=horizon_minutes)
                forward_candles = [c for c in group_candles[i + 1 :] if c.open_time >= entry_time]

                if not forward_candles or forward_candles[-1].close_time < time_barrier:
                    # Not enough forward history yet to know the true outcome -- skip
                    # rather than guess.
                    continue

                first_hit, exit_price, label_end_time = _first_barrier_hit(
                    entry_reference_price, upper_barrier, lower_barrier, time_barrier, forward_candles
                )
                if first_hit is None:
                    continue
                # _first_barrier_hit only returns a non-None first_hit alongside a
                # non-None exit_price (every branch sets both together) -- narrow the
                # type for the type checker, and as a runtime invariant check.
                assert exit_price is not None

                gross_return_bps = (exit_price - entry_reference_price) / entry_reference_price * BPS
                net_return_bps = gross_return_bps - cost_bps

                if first_hit == "LOWER":
                    label = "LOSS"
                elif first_hit == "UPPER":
                    label = "PROFIT" if net_return_bps > 0 else "LOSS"
                else:
                    label = "TIMEOUT"

                rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": tf_value,
                        "entry_open_time": entry_candle.open_time,
                        "entry_time": entry_time,
                        "horizon_minutes": horizon_minutes,
                        "entry_reference_price": str(entry_reference_price),
                        "upper_barrier": str(upper_barrier),
                        "lower_barrier": str(lower_barrier),
                        "time_barrier": time_barrier,
                        "first_barrier_hit": first_hit,
                        "gross_return_bps": float(gross_return_bps),
                        "estimated_cost_bps": float(cost_bps),
                        "net_return_bps": float(net_return_bps),
                        "label": label,
                        "label_end_time": label_end_time,
                    }
                )

    columns = [
        "symbol", "timeframe", "entry_open_time", "entry_time", "horizon_minutes",
        "entry_reference_price", "upper_barrier", "lower_barrier", "time_barrier",
        "first_barrier_hit", "gross_return_bps", "estimated_cost_bps", "net_return_bps",
        "label", "label_end_time",
    ]
    df = pd.DataFrame(rows, columns=columns)
    if not df.empty:
        for col in ("entry_open_time", "entry_time", "time_barrier", "label_end_time"):
            df[col] = pd.to_datetime(df[col], utc=True)
    return df
