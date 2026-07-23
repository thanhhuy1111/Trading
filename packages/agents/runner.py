import json
from typing import List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.agents.breakout import BreakoutAgent
from packages.agents.models import AgentEvaluationContext, AgentSignal
from packages.agents.regime import MarketRegimeAgent
from packages.agents.reversion import MeanReversionAgent
from packages.agents.trend import TrendAgent
from packages.common.logger import logger
from packages.events.envelope import DomainEventEnvelope
from packages.features.models import FeatureSnapshot
from packages.outbox.repository import OutboxRepository


class AgentRunner:
    """Orchestrates independent strategy agents upon receiving feature snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.regime_agent = MarketRegimeAgent()
        self.trend_agent = TrendAgent()
        self.reversion_agent = MeanReversionAgent()
        self.breakout_agent = BreakoutAgent()
        self.outbox_repo = OutboxRepository(session)

    async def run_agents(self, snapshot: FeatureSnapshot) -> List[AgentSignal]:
        eval_ctx = AgentEvaluationContext(
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            as_of_time=snapshot.as_of_time,
            feature_snapshot=snapshot,
            market_regime=self.regime_agent.classify_regime(
                AgentEvaluationContext(
                    exchange=snapshot.exchange,
                    symbol=snapshot.symbol,
                    timeframe=snapshot.timeframe,
                    as_of_time=snapshot.as_of_time,
                    feature_snapshot=snapshot,
                    market_regime="UNKNOWN",
                    data_quality_status="HEALTHY"
                )
            ),
            data_quality_status="HEALTHY"
        )

        signals: List[AgentSignal] = []

        # Run Trend Agent
        try:
            sig = await self.trend_agent.evaluate(eval_ctx)
            signals.append(sig)
        except Exception as e:
            logger.error("TrendAgent evaluation error", extra={"error": str(e), "agent": self.trend_agent.agent_id})

        # Run Mean Reversion Agent
        try:
            sig = await self.reversion_agent.evaluate(eval_ctx)
            signals.append(sig)
        except Exception as e:
            logger.error(
                "MeanReversionAgent evaluation error", extra={"error": str(e), "agent": self.reversion_agent.agent_id}
            )

        # Run Breakout Agent
        try:
            sig = await self.breakout_agent.evaluate(eval_ctx)
            signals.append(sig)
        except Exception as e:
            logger.error(
                "BreakoutAgent evaluation error", extra={"error": str(e), "agent": self.breakout_agent.agent_id}
            )

        # Save signals & publish outbox events
        for sig in signals:
            await self._save_signal(sig)
            event = DomainEventEnvelope.create(
                event_type="agent.signal_created",
                aggregate_type="agent_signal",
                aggregate_id=str(sig.signal_id),
                payload=sig.model_dump(mode="json"),
                producer="agent_runner"
            )
            await self.outbox_repo.save_event(event)

        return signals

    async def _save_signal(self, sig: AgentSignal) -> None:
        query = text("""
            INSERT INTO agent_signals (
                signal_id, agent_id, agent_name, agent_version, strategy_type, exchange, symbol, timeframe,
                action, expected_return_bps, confidence, horizon_minutes, reference_price, invalidation_price,
                suggested_stop_price, suggested_take_profit_price, market_regime, feature_snapshot_id,
                feature_set_version, feature_as_of_time, generated_at, expires_at, reason_codes, explanation,
                quality_flags, schema_version, created_at
            ) VALUES (
                :signal_id, :agent_id, :agent_name, :agent_version, :strategy_type, :exchange, :symbol, :timeframe,
                :action, :expected_return_bps, :confidence, :horizon_minutes, :reference_price, :invalidation_price,
                :suggested_stop_price, :suggested_take_profit_price, :market_regime, :feature_snapshot_id,
                :feature_set_version, :feature_as_of_time, :generated_at, :expires_at, :reason_codes, :explanation,
                :quality_flags, :schema_version, NOW()
            )
            ON CONFLICT (agent_id, exchange, symbol, timeframe, feature_as_of_time) DO NOTHING
        """)

        params = {
            "signal_id": str(sig.signal_id),
            "agent_id": sig.agent_id,
            "agent_name": sig.agent_name,
            "agent_version": sig.agent_version,
            "strategy_type": sig.strategy_type.value,
            "exchange": sig.exchange,
            "symbol": sig.symbol,
            "timeframe": sig.timeframe.value,
            "action": sig.action.value,
            "expected_return_bps": str(sig.expected_return_bps) if sig.expected_return_bps is not None else None,
            "confidence": str(sig.confidence),
            "horizon_minutes": sig.horizon_minutes,
            "reference_price": str(sig.reference_price),
            "invalidation_price": str(sig.invalidation_price) if sig.invalidation_price is not None else None,
            "suggested_stop_price": str(sig.suggested_stop_price) if sig.suggested_stop_price is not None else None,
            "suggested_take_profit_price": (
                str(sig.suggested_take_profit_price) if sig.suggested_take_profit_price is not None else None
            ),
            "market_regime": sig.market_regime.value,
            "feature_snapshot_id": str(sig.feature_snapshot_id),
            "feature_set_version": sig.feature_set_version,
            "feature_as_of_time": sig.feature_as_of_time,
            "generated_at": sig.generated_at,
            "expires_at": sig.expires_at,
            "reason_codes": json.dumps(sig.reason_codes),
            "explanation": json.dumps(sig.explanation),
            "quality_flags": json.dumps(sig.quality_flags),
            "schema_version": sig.schema_version,
        }

        await self.session.execute(query, params)
