from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import (
    AgentEvaluationContext,
    AgentSignal,
    MarketRegime,
    SignalAction,
    StrategyType,
)


class MeanReversionAgent:
    """Mean Reversion Strategy Agent."""

    def __init__(self, agent_id: str = "reversion_agent_v1", version: str = "1.0.0"):
        self._agent_id = agent_id
        self._version = version

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return "Mean Reversion Agent"

    @property
    def version(self) -> str:
        return self._version

    @property
    def required_feature_set(self) -> str:
        return "standard_v1"

    async def evaluate(self, context: AgentEvaluationContext) -> AgentSignal:
        now = datetime.now(timezone.utc)
        vals = context.feature_snapshot.values
        regime = context.market_regime

        rsi = vals.get("rsi_14")
        zscore = vals.get("zscore_20")

        reasons = []
        action = SignalAction.NO_SIGNAL
        confidence = Decimal("0.50")

        if regime not in [MarketRegime.SIDEWAYS, MarketRegime.LOW_VOLATILITY]:
            reasons.append("REGIME_NOT_SUPPORTED")
        else:
            if rsi is not None and zscore is not None:
                rsi_dec = Decimal(str(rsi))
                z_dec = Decimal(str(zscore))

                if rsi_dec < Decimal("30.0") or z_dec < Decimal("-1.8"):
                    action = SignalAction.LONG
                    confidence = Decimal("0.70")
                    reasons.append("OVERSOLD_CONDITION")
                elif rsi_dec > Decimal("70.0") or z_dec > Decimal("1.8"):
                    action = SignalAction.SHORT
                    confidence = Decimal("0.70")
                    reasons.append("OVERBOUGHT_CONDITION")
                else:
                    reasons.append("INSIDE_NEUTRAL_ZONE")

        ref_price = Decimal("65000.00")
        is_long = (action == SignalAction.LONG)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.name,
            agent_version=self.version,
            strategy_type=StrategyType.MEAN_REVERSION,
            exchange=context.exchange,
            symbol=context.symbol,
            timeframe=context.timeframe,
            action=action,
            confidence=confidence,
            horizon_minutes=30,
            reference_price=ref_price,
            invalidation_price=ref_price * Decimal("0.985") if is_long else ref_price * Decimal("1.015"),
            suggested_stop_price=ref_price * Decimal("0.980") if is_long else ref_price * Decimal("1.020"),
            suggested_take_profit_price=ref_price * Decimal("1.020") if is_long else ref_price * Decimal("0.980"),
            market_regime=regime,
            feature_snapshot_id=context.feature_snapshot.snapshot_id,
            feature_set_version=context.feature_snapshot.feature_set_version,
            feature_as_of_time=context.feature_snapshot.as_of_time,
            generated_at=now,
            expires_at=now + timedelta(minutes=30),
            reason_codes=reasons,
            explanation=[f"Evaluated mean reversion for {context.symbol} on {context.timeframe.value} timeframe."]
        )
