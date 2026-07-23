import hashlib
import json
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class StrategyConfig(BaseModel):
    """Versioned, hashable strategy configuration.

    All agent thresholds live here (not hardcoded in agent source) so that the
    exact parameters that produced a decision can be recorded in the decision
    lineage via `config_hash`. Values are the historical defaults so that
    behaviour is unchanged unless a caller supplies an alternative config.
    """

    model_config = ConfigDict(frozen=True)

    version: str = "1.0.0"

    # --- Regime classification ---
    regime_high_vol_threshold: Decimal = Decimal("0.05")
    regime_adx_trend_threshold: Decimal = Decimal("25.0")
    regime_slope_up_threshold: Decimal = Decimal("0.001")
    regime_slope_down_threshold: Decimal = Decimal("-0.001")

    # --- Agent confidences (heuristic scores) ---
    trend_confidence: Decimal = Decimal("0.75")
    reversion_confidence: Decimal = Decimal("0.70")
    breakout_confidence: Decimal = Decimal("0.80")
    neutral_confidence: Decimal = Decimal("0.50")

    # --- Mean reversion thresholds ---
    reversion_rsi_oversold: Decimal = Decimal("30.0")
    reversion_rsi_overbought: Decimal = Decimal("70.0")
    reversion_zscore_threshold: Decimal = Decimal("1.8")

    # --- Breakout thresholds ---
    breakout_rvol_threshold: Decimal = Decimal("1.2")

    # --- Price structure multiples (fractions of reference price) ---
    trend_stop_pct: Decimal = Decimal("0.03")
    trend_take_profit_pct: Decimal = Decimal("0.05")
    trend_invalidation_pct: Decimal = Decimal("0.02")

    reversion_stop_pct: Decimal = Decimal("0.02")
    reversion_take_profit_pct: Decimal = Decimal("0.02")
    reversion_invalidation_pct: Decimal = Decimal("0.015")

    breakout_stop_pct: Decimal = Decimal("0.03")
    breakout_take_profit_pct: Decimal = Decimal("0.06")
    breakout_invalidation_pct: Decimal = Decimal("0.02")

    # Allocator-level structure used when building a symbol TradeIntent (long spot).
    intent_stop_pct: Decimal = Decimal("0.03")
    intent_take_profit_pct: Decimal = Decimal("0.05")
    intent_invalidation_pct: Decimal = Decimal("0.02")

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            {k: str(v) for k, v in self.model_dump().items()},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


default_strategy_config = StrategyConfig()
