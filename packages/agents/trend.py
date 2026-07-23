from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import (
    AgentEvaluationContext,
    AgentSignal,
    MarketRegime,
    SignalAction,
    StrategyType,
)


class TrendAgent:
    """Trend Following Strategy Agent."""

    def __init__(self, agent_id: str = "trend_agent_v1", version: str = "1.0.0"):
        self._agent_id = agent_id
        self._version = version

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return "Trend Following Agent"

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

        ema_slope = vals.get("ema_20_slope")

        reasons = []
        action = SignalAction.NO_SIGNAL
        confidence = Decimal("0.50")

        if regime == MarketRegime.TREND_UP and ema_slope is not None and Decimal(str(ema_slope)) > Decimal("0"):
            action = SignalAction.LONG
            confidence = Decimal("0.75")
            reasons.append("UPTREND_CONFIRMED")
            reasons.append("EMA_SLOPE_POSITIVE")
        elif regime == MarketRegime.TREND_DOWN and ema_slope is not None and Decimal(str(ema_slope)) < Decimal("0"):
            action = SignalAction.SHORT
            confidence = Decimal("0.75")
            reasons.append("DOWNTREND_CONFIRMED")
            reasons.append("EMA_SLOPE_NEGATIVE")
        else:
            reasons.append("REGIME_NOT_TRENDING")

        ref_price = Decimal("65000.00")
        is_long = (action == SignalAction.LONG)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.name,
            agent_version=self.version,
            strategy_type=StrategyType.TREND_FOLLOWING,
            exchange=context.exchange,
            symbol=context.symbol,
            timeframe=context.timeframe,
            action=action,
            confidence=confidence,
            horizon_minutes=60,
            reference_price=ref_price,
            invalidation_price=ref_price * Decimal("0.98") if is_long else ref_price * Decimal("1.02"),
            suggested_stop_price=ref_price * Decimal("0.97") if is_long else ref_price * Decimal("1.03"),
            suggested_take_profit_price=ref_price * Decimal("1.05") if is_long else ref_price * Decimal("0.95"),
            market_regime=regime,
            feature_snapshot_id=context.feature_snapshot.snapshot_id,
            feature_set_version=context.feature_snapshot.feature_set_version,
            feature_as_of_time=context.feature_snapshot.as_of_time,
            generated_at=now,
            expires_at=now + timedelta(minutes=60),
            reason_codes=reasons,
            explanation=[f"Evaluated trend alignment for {context.symbol} on {context.timeframe.value} timeframe."]
        )
