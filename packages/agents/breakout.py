from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import (
    AgentEvaluationContext,
    AgentSignal,
    SignalAction,
    StrategyType,
)
from packages.agents.pricing import expected_return_bps as _expected_return_bps
from packages.agents.pricing import price_levels as _price_levels
from packages.agents.strategy_config import default_strategy_config


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

        cfg = context.strategy_config or default_strategy_config
        db = vals.get("donchian_breakout_20")
        rvol = vals.get("relative_volume_20")

        reasons = []
        action = SignalAction.NO_SIGNAL
        confidence = cfg.neutral_confidence

        if db is not None:
            db_dec = Decimal(str(db))
            rvol_dec = Decimal(str(rvol)) if rvol is not None else Decimal("1.0")

            if db_dec > Decimal("0") and rvol_dec >= cfg.breakout_rvol_threshold:
                action = SignalAction.LONG
                confidence = cfg.breakout_confidence
                reasons.append("BULLISH_DONCHIAN_BREAKOUT")
                reasons.append("VOLUME_EXPANSION_CONFIRMED")
            elif db_dec < Decimal("0") and rvol_dec >= cfg.breakout_rvol_threshold:
                action = SignalAction.SHORT
                confidence = cfg.breakout_confidence
                reasons.append("BEARISH_DONCHIAN_BREAKOUT")
                reasons.append("VOLUME_EXPANSION_CONFIRMED")
            else:
                reasons.append("NO_CONFIRMED_BREAKOUT")

        ref = context.reference_price if (context.reference_price and context.reference_price > 0) else None
        is_long = (action == SignalAction.LONG)
        levels = _price_levels(
            ref, is_long, cfg.breakout_stop_pct, cfg.breakout_take_profit_pct, cfg.breakout_invalidation_pct
        )
        expected = _expected_return_bps(ref, action, levels["take_profit"], confidence)
        if expected is None and action in (SignalAction.LONG, SignalAction.SHORT):
            reasons.append("EXPECTED_RETURN_UNAVAILABLE")

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
            expected_return_bps=expected,
            horizon_minutes=45,
            reference_price=levels["reference"],
            invalidation_price=levels["invalidation"],
            suggested_stop_price=levels["stop"],
            suggested_take_profit_price=levels["take_profit"],
            market_regime=regime,
            feature_snapshot_id=context.feature_snapshot.snapshot_id,
            feature_set_version=context.feature_snapshot.feature_set_version,
            feature_as_of_time=context.feature_snapshot.as_of_time,
            generated_at=now,
            expires_at=now + timedelta(minutes=45),
            reason_codes=reasons,
            explanation=[f"Evaluated breakout for {context.symbol} on {context.timeframe.value} timeframe."]
        )
