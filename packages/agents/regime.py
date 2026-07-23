from decimal import Decimal

from packages.agents.models import AgentEvaluationContext, MarketRegime


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

        adx = vals.get("adx_14")
        ema_slope = vals.get("ema_20_slope")
        vol = vals.get("volatility_20")

        if adx is None or ema_slope is None:
            return MarketRegime.UNKNOWN

        adx_dec = Decimal(str(adx))
        slope_dec = Decimal(str(ema_slope))
        vol_dec = Decimal(str(vol)) if vol is not None else Decimal("0")

        if vol_dec > Decimal("0.05"):
            return MarketRegime.HIGH_VOLATILITY

        if adx_dec >= Decimal("25.0"):
            if slope_dec > Decimal("0.001"):
                return MarketRegime.TREND_UP
            elif slope_dec < Decimal("-0.001"):
                return MarketRegime.TREND_DOWN

        return MarketRegime.SIDEWAYS
