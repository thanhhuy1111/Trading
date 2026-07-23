from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import (
    AgentEvaluationContext,
    AgentSignal,
    SignalAction,
    StrategyType,
)


class BreakoutAgent:
    """Breakout Strategy Agent."""

    def __init__(self, agent_id: str = "breakout_agent_v1", version: str = "1.0.0"):
        self._agent_id = agent_id
        self._version = version

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return "Breakout Strategy Agent"

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

        db = vals.get("donchian_breakout_20")
        rvol = vals.get("relative_volume_20")

        reasons = []
        action = SignalAction.NO_SIGNAL
        confidence = Decimal("0.50")

        if db is not None:
            db_dec = Decimal(str(db))
            rvol_dec = Decimal(str(rvol)) if rvol is not None else Decimal("1.0")

            if db_dec > Decimal("0") and rvol_dec >= Decimal("1.2"):
                action = SignalAction.LONG
                confidence = Decimal("0.80")
                reasons.append("BULLISH_DONCHIAN_BREAKOUT")
                reasons.append("VOLUME_EXPANSION_CONFIRMED")
            elif db_dec < Decimal("0") and rvol_dec >= Decimal("1.2"):
                action = SignalAction.SHORT
                confidence = Decimal("0.80")
                reasons.append("BEARISH_DONCHIAN_BREAKOUT")
                reasons.append("VOLUME_EXPANSION_CONFIRMED")
            else:
                reasons.append("NO_CONFIRMED_BREAKOUT")

        ref_price = Decimal("65000.00")
        is_long = (action == SignalAction.LONG)

        return AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.name,
            agent_version=self.version,
            strategy_type=StrategyType.BREAKOUT,
            exchange=context.exchange,
            symbol=context.symbol,
            timeframe=context.timeframe,
            action=action,
            confidence=confidence,
            horizon_minutes=45,
            reference_price=ref_price,
            invalidation_price=ref_price * Decimal("0.98") if is_long else ref_price * Decimal("1.02"),
            suggested_stop_price=ref_price * Decimal("0.97") if is_long else ref_price * Decimal("1.03"),
            suggested_take_profit_price=ref_price * Decimal("1.06") if is_long else ref_price * Decimal("0.94"),
            market_regime=regime,
            feature_snapshot_id=context.feature_snapshot.snapshot_id,
            feature_set_version=context.feature_snapshot.feature_set_version,
            feature_as_of_time=context.feature_snapshot.as_of_time,
            generated_at=now,
            expires_at=now + timedelta(minutes=45),
            reason_codes=reasons,
            explanation=[f"Evaluated breakout for {context.symbol} on {context.timeframe.value} timeframe."]
        )
