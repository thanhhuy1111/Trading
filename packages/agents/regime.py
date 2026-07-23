from decimal import Decimal

from packages.agents.models import AgentEvaluationContext, MarketRegime
from packages.agents.strategy_config import default_strategy_config


class MarketRegimeAgent:
    """Classifies market regime into TREND_UP, TREND_DOWN, SIDEWAYS, HIGH_VOLATILITY, etc."""

    def __init__(self, agent_id: str = "regime_agent_v1", version: str = "1.0.0"):
        self._agent_id = agent_id
        self._version = version

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return "Market Regime Agent"

    @property
    def version(self) -> str:
        return self._version

    def classify_regime(self, context: AgentEvaluationContext) -> MarketRegime:
        vals = context.feature_snapshot.values
        cfg = context.strategy_config or default_strategy_config

        adx = vals.get("adx_14")
        ema_slope = vals.get("ema_20_slope")
        vol = vals.get("volatility_20")

        if adx is None or ema_slope is None:
            return MarketRegime.UNKNOWN

        adx_dec = Decimal(str(adx))
        slope_dec = Decimal(str(ema_slope))
        vol_dec = Decimal(str(vol)) if vol is not None else Decimal("0")

        if vol_dec > cfg.regime_high_vol_threshold:
            return MarketRegime.HIGH_VOLATILITY

        if adx_dec >= cfg.regime_adx_trend_threshold:
            if slope_dec > cfg.regime_slope_up_threshold:
                return MarketRegime.TREND_UP
            elif slope_dec < cfg.regime_slope_down_threshold:
                return MarketRegime.TREND_DOWN

        return MarketRegime.SIDEWAYS
