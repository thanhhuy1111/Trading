"""Controlled model-configuration grid for the Alpha Research Campaign.

Deliberately NOT a full factorial grid search. `default_strategy_config` has ~20 tunable
fields; brute-forcing every combination (a) is not affordable at this scale and (b) invites
multiple-testing / overfitting to noise, which is exactly the failure mode a real promotion
gate exists to catch. Instead this is a curated, one-axis-at-a-time (plus a couple of named
"bundle" hypotheses) design: every variant changes only the parameters relevant to the
hypothesis it tests, so a pass/fail result is individually interpretable.

Each variant is a dict of field-name -> override value (kept as a plain, picklable dict
rather than a `StrategyConfig` instance) so campaign worker processes can reconstruct the
config locally without pickling pydantic objects across the process-pool boundary.
"""

from decimal import Decimal
from typing import Dict

from packages.agents.strategy_config import StrategyConfig, default_strategy_config

# name -> (rationale, field overrides applied on top of default_strategy_config)
CONFIG_GRID: Dict[str, tuple] = {
    "baseline": (
        "Unmodified production defaults. Reference point every other variant is judged against.",
        {},
    ),
    "trend_confidence_low": (
        "Admits lower-conviction trend signals through the critic/consensus stage.",
        {"trend_confidence": Decimal("0.65")},
    ),
    "trend_confidence_high": (
        "Only acts on high-conviction trend signals.",
        {"trend_confidence": Decimal("0.85")},
    ),
    "reversion_tight_bands": (
        "Tighter RSI/z-score entry bands: more mean-reversion signals fire.",
        {
            "reversion_rsi_oversold": Decimal("35.0"),
            "reversion_rsi_overbought": Decimal("65.0"),
            "reversion_zscore_threshold": Decimal("1.5"),
        },
    ),
    "reversion_loose_bands": (
        "Looser RSI/z-score entry bands: only extreme dislocations trigger.",
        {
            "reversion_rsi_oversold": Decimal("25.0"),
            "reversion_rsi_overbought": Decimal("75.0"),
            "reversion_zscore_threshold": Decimal("2.2"),
        },
    ),
    "breakout_sensitive": (
        "Lower relative-volume bar for breakout confirmation: more breakout signals fire.",
        {"breakout_rvol_threshold": Decimal("1.1")},
    ),
    "breakout_strict": (
        "Higher relative-volume bar for breakout confirmation: fewer, stronger signals.",
        {"breakout_rvol_threshold": Decimal("1.5")},
    ),
    "tight_risk_structure": (
        "Tighter stops/targets across all agents (~0.7x default distance): faster exits.",
        {
            "trend_stop_pct": Decimal("0.021"), "trend_take_profit_pct": Decimal("0.035"),
            "reversion_stop_pct": Decimal("0.014"), "reversion_take_profit_pct": Decimal("0.014"),
            "breakout_stop_pct": Decimal("0.021"), "breakout_take_profit_pct": Decimal("0.042"),
            "intent_stop_pct": Decimal("0.021"), "intent_take_profit_pct": Decimal("0.035"),
        },
    ),
    "wide_risk_structure": (
        "Wider stops/targets across all agents (~1.4x default distance): more room per trade.",
        {
            "trend_stop_pct": Decimal("0.042"), "trend_take_profit_pct": Decimal("0.07"),
            "reversion_stop_pct": Decimal("0.028"), "reversion_take_profit_pct": Decimal("0.028"),
            "breakout_stop_pct": Decimal("0.042"), "breakout_take_profit_pct": Decimal("0.084"),
            "intent_stop_pct": Decimal("0.042"), "intent_take_profit_pct": Decimal("0.07"),
        },
    ),
    "high_conviction_only": (
        "Bundle: raises every agent's confidence bar simultaneously (fewer, higher-quality trades).",
        {
            "trend_confidence": Decimal("0.85"), "reversion_confidence": Decimal("0.80"),
            "breakout_confidence": Decimal("0.90"), "neutral_confidence": Decimal("0.55"),
        },
    ),
    "low_conviction_admitted": (
        "Bundle: lowers every agent's confidence bar simultaneously (more, noisier trades).",
        {
            "trend_confidence": Decimal("0.65"), "reversion_confidence": Decimal("0.60"),
            "breakout_confidence": Decimal("0.70"), "neutral_confidence": Decimal("0.45"),
        },
    ),
    "momentum_focus": (
        "Bundle: favors trend/breakout conviction over mean-reversion.",
        {
            "trend_confidence": Decimal("0.82"), "breakout_confidence": Decimal("0.85"),
            "reversion_confidence": Decimal("0.60"),
        },
    ),
    "mean_reversion_focus": (
        "Bundle: favors mean-reversion conviction over trend/breakout.",
        {
            "reversion_confidence": Decimal("0.82"), "trend_confidence": Decimal("0.62"),
            "breakout_confidence": Decimal("0.65"),
        },
    ),
    "conservative_regime": (
        "Stricter regime classification: higher ADX bar for 'trending', lower vol bar for 'high-vol'.",
        {
            "regime_adx_trend_threshold": Decimal("30.0"),
            "regime_high_vol_threshold": Decimal("0.04"),
        },
    ),
    "aggressive_regime": (
        "Looser regime classification: lower ADX bar for 'trending', higher vol bar for 'high-vol'.",
        {
            "regime_adx_trend_threshold": Decimal("20.0"),
            "regime_high_vol_threshold": Decimal("0.07"),
        },
    ),
}


def build_strategy_config(overrides: Dict) -> StrategyConfig:
    base = default_strategy_config.model_dump()
    base.update(overrides)
    return StrategyConfig(**base)


def iter_variants():
    for name, (rationale, overrides) in CONFIG_GRID.items():
        yield name, rationale, overrides
