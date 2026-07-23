from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import (
    AgentEvaluationContext,
    AgentSignal,
    MarketRegime,
    SignalAction,
    StrategyType,
)
from packages.agents.pricing import expected_return_bps as _expected_return_bps
from packages.agents.pricing import price_levels as _price_levels
from packages.agents.strategy_config import default_strategy_config


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
        cfg = context.strategy_config or default_strategy_config

        ema_slope = vals.get("ema_20_slope")

        reasons = []
        action = SignalAction.NO_SIGNAL
        confidence = cfg.neutral_confidence

        if regime == MarketRegime.TREND_UP and ema_slope is not None and Decimal(str(ema_slope)) > Decimal("0"):
            action = SignalAction.LONG
            confidence = cfg.trend_confidence
            reasons.append("UPTREND_CONFIRMED")
            reasons.append("EMA_SLOPE_POSITIVE")
        elif regime == MarketRegime.TREND_DOWN and ema_slope is not None and Decimal(str(ema_slope)) < Decimal("0"):
            action = SignalAction.SHORT
            confidence = cfg.trend_confidence
            reasons.append("DOWNTREND_CONFIRMED")
            reasons.append("EMA_SLOPE_NEGATIVE")
        else:
            reasons.append("REGIME_NOT_TRENDING")

        ref = context.reference_price if (context.reference_price and context.reference_price > 0) else None
        is_long = (action == SignalAction.LONG)
        levels = _price_levels(
            ref, is_long, cfg.trend_stop_pct, cfg.trend_take_profit_pct, cfg.trend_invalidation_pct
        )
        expected = _expected_return_bps(ref, action, levels["take_profit"], confidence)
        if expected is None and action in (SignalAction.LONG, SignalAction.SHORT):
            reasons.append("EXPECTED_RETURN_UNAVAILABLE")

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
            expected_return_bps=expected,
            horizon_minutes=60,
            reference_price=levels["reference"],
            invalidation_price=levels["invalidation"],
            suggested_stop_price=levels["stop"],
            suggested_take_profit_price=levels["take_profit"],
            market_regime=regime,
            feature_snapshot_id=context.feature_snapshot.snapshot_id,
            feature_set_version=context.feature_snapshot.feature_set_version,
            feature_as_of_time=context.feature_snapshot.as_of_time,
            generated_at=now,
            expires_at=now + timedelta(minutes=60),
            reason_codes=reasons,
            explanation=[f"Evaluated trend alignment for {context.symbol} on {context.timeframe.value} timeframe."]
        )
