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

        cfg = context.strategy_config or default_strategy_config
        rsi = vals.get("rsi_14")
        zscore = vals.get("zscore_20")

        reasons = []
        action = SignalAction.NO_SIGNAL
        confidence = cfg.neutral_confidence

        if regime not in [MarketRegime.SIDEWAYS, MarketRegime.LOW_VOLATILITY]:
            reasons.append("REGIME_NOT_SUPPORTED")
        else:
            if rsi is not None and zscore is not None:
                rsi_dec = Decimal(str(rsi))
                z_dec = Decimal(str(zscore))

                if rsi_dec < cfg.reversion_rsi_oversold or z_dec < -cfg.reversion_zscore_threshold:
                    action = SignalAction.LONG
                    confidence = cfg.reversion_confidence
                    reasons.append("OVERSOLD_CONDITION")
                elif rsi_dec > cfg.reversion_rsi_overbought or z_dec > cfg.reversion_zscore_threshold:
                    action = SignalAction.SHORT
                    confidence = cfg.reversion_confidence
                    reasons.append("OVERBOUGHT_CONDITION")
                else:
                    reasons.append("INSIDE_NEUTRAL_ZONE")

        ref = context.reference_price if (context.reference_price and context.reference_price > 0) else None
        is_long = (action == SignalAction.LONG)
        levels = _price_levels(
            ref, is_long, cfg.reversion_stop_pct, cfg.reversion_take_profit_pct, cfg.reversion_invalidation_pct
        )
        expected = _expected_return_bps(ref, action, levels["take_profit"], confidence)
        if expected is None and action in (SignalAction.LONG, SignalAction.SHORT):
            reasons.append("EXPECTED_RETURN_UNAVAILABLE")

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
            expected_return_bps=expected,
            horizon_minutes=30,
            reference_price=levels["reference"],
            invalidation_price=levels["invalidation"],
            suggested_stop_price=levels["stop"],
            suggested_take_profit_price=levels["take_profit"],
            market_regime=regime,
            feature_snapshot_id=context.feature_snapshot.snapshot_id,
            feature_set_version=context.feature_snapshot.feature_set_version,
            feature_as_of_time=context.feature_snapshot.as_of_time,
            generated_at=now,
            expires_at=now + timedelta(minutes=30),
            reason_codes=reasons,
            explanation=[f"Evaluated mean reversion for {context.symbol} on {context.timeframe.value} timeframe."]
        )
