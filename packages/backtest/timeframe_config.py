"""Per-timeframe research configuration.

Explicit requirement (docs/research/TIMEFRAME_RESEARCH_POLICY.md): 1h and 4h must NOT reuse
1D's config values. Every field below is set independently per timeframe, with the reasoning
documented in the policy doc rather than copied from whatever number happened to work on 1D.

`get_timeframe_config` raises for any timeframe without an explicit entry — there is
deliberately no fallback default, matching the "no 1h config borrowed from 1D" principle
structurally rather than as a convention someone could forget.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Dict

from pydantic import BaseModel

from packages.market_data.models import Timeframe


class TimeframeConfig(BaseModel):
    timeframe: Timeframe

    # Feature computation window, in bars. Kept at the same bar count across timeframes
    # because it exists to satisfy indicator lookback requirements (max 28 bars for the
    # standard_v1 feature set — see FEATURE_LOOKBACK_WINDOW in packages/backtest/engine.py),
    # which is a property of the indicators, not of calendar time.
    feature_lookback_bars: int

    # How far forward a decision's outcome is evaluated for meta-labeling (Checkpoint 3).
    # Timeframe-specific: a 1h swing plays out over hours, a 1D swing over days.
    label_horizon: timedelta

    # Triple-barrier levels as a fraction of entry price, sqrt-time-scaled down from the 1D
    # baseline (upper=5%, lower=3%, matching packages/agents/strategy_config.py's
    # trend_take_profit_pct/trend_stop_pct defaults) using bars_1d / bars_tf as the time
    # ratio — a standard volatility-scaling heuristic, not fit to any backtest result.
    upper_barrier_pct: Decimal
    lower_barrier_pct: Decimal

    # Purge/embargo for walk-forward CV: set to 1x label_horizon, which is the actual
    # statistical requirement (remove samples whose label window can overlap the train/test
    # boundary) rather than an arbitrary calendar constant.
    purge_period: timedelta
    embargo_period: timedelta

    # Cost assumptions are NOT timeframe-dependent by design — they reflect the exchange fee
    # schedule and market microstructure (packages/governance/cost_estimator.py), not candle
    # aggregation. Kept identical across timeframes deliberately, not by omission.
    estimated_fee_bps: Decimal
    estimated_spread_bps: Decimal
    estimated_slippage_bps: Decimal

    # Minimum OOS trades required before this timeframe's results are gate-eligible. Higher
    # for higher-frequency timeframes: trades close together in time on 1h data are less
    # statistically independent than on 1D data, so the same raw count carries less evidence.
    minimum_trade_count: int

    # How long a generated proposal stays valid: one bar — after the next bar closes, the
    # features/regime it was computed from are stale.
    proposal_expiry: timedelta


TIMEFRAME_CONFIGS: Dict[Timeframe, TimeframeConfig] = {
    Timeframe.D1: TimeframeConfig(
        timeframe=Timeframe.D1,
        feature_lookback_bars=250,
        label_horizon=timedelta(days=10),
        upper_barrier_pct=Decimal("0.05"),
        lower_barrier_pct=Decimal("0.03"),
        purge_period=timedelta(days=10),
        embargo_period=timedelta(days=10),
        estimated_fee_bps=Decimal("10.0"),
        estimated_spread_bps=Decimal("2.0"),
        estimated_slippage_bps=Decimal("5.0"),
        minimum_trade_count=20,
        proposal_expiry=timedelta(days=1),
    ),
    Timeframe.H4: TimeframeConfig(
        timeframe=Timeframe.H4,
        feature_lookback_bars=250,
        label_horizon=timedelta(hours=48),   # ~2 days: 12 bars
        # sqrt(10 days / 2 days) = sqrt(5) ~= 2.24 scaling factor down from the 1D barriers
        upper_barrier_pct=Decimal("0.0223"),
        lower_barrier_pct=Decimal("0.0134"),
        purge_period=timedelta(hours=48),
        embargo_period=timedelta(hours=48),
        estimated_fee_bps=Decimal("10.0"),
        estimated_spread_bps=Decimal("2.0"),
        estimated_slippage_bps=Decimal("5.0"),
        minimum_trade_count=30,
        proposal_expiry=timedelta(hours=4),
    ),
    Timeframe.H1: TimeframeConfig(
        timeframe=Timeframe.H1,
        feature_lookback_bars=250,
        label_horizon=timedelta(hours=24),   # ~1 day: 24 bars
        # sqrt(10 days / 1 day) = sqrt(10) ~= 3.16 scaling factor down from the 1D barriers
        upper_barrier_pct=Decimal("0.0158"),
        lower_barrier_pct=Decimal("0.0095"),
        purge_period=timedelta(hours=24),
        embargo_period=timedelta(hours=24),
        estimated_fee_bps=Decimal("10.0"),
        estimated_spread_bps=Decimal("2.0"),
        estimated_slippage_bps=Decimal("5.0"),
        minimum_trade_count=50,
        proposal_expiry=timedelta(hours=1),
    ),
}


def get_timeframe_config(timeframe: Timeframe) -> TimeframeConfig:
    """Raises KeyError (not a silent default) for any timeframe without an explicit,
    independently-set configuration — there is no "borrow the nearest timeframe's config"
    path."""
    if timeframe not in TIMEFRAME_CONFIGS:
        raise KeyError(
            f"NO_TIMEFRAME_CONFIG: {timeframe.value} has no explicit TimeframeConfig entry. "
            "Add one to TIMEFRAME_CONFIGS — do not reuse another timeframe's config."
        )
    return TIMEFRAME_CONFIGS[timeframe]
