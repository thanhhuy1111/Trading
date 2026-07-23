"""Shared, deterministic, DB-free decision core.

This is the single runtime orchestrator that turns a closed-candle history into a
governance decision, running the REAL components:

    FeaturePipeline -> MarketRegimeAgent -> {Trend, MeanReversion, Breakout} agents
    -> CriticAgent -> SignalConsensusEngine -> MetaAllocator -> TradeIntent | NO_TRADE

It uses the exact same agent classes and the same critic / consensus / allocator
singletons that the DB-persisting AgentRunner / GovernancePipeline use, but performs
no database or outbox I/O so it can run inside the paper and backtest loops.

No fabricated confidence / edge / regime values are produced here; everything is
derived from features computed strictly from candles with close_time <= as_of_time.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from packages.agents.breakout import BreakoutAgent
from packages.agents.models import AgentEvaluationContext, AgentSignal, MarketRegime
from packages.agents.regime import MarketRegimeAgent
from packages.agents.reversion import MeanReversionAgent
from packages.agents.strategy_config import StrategyConfig, default_strategy_config
from packages.agents.trend import TrendAgent
from packages.features.models import FeatureComputationRequest, FeatureSnapshot
from packages.governance.allocator import meta_allocator
from packages.governance.consensus import signal_consensus_engine
from packages.governance.critic import critic_agent
from packages.governance.models import (
    AllocationDecision,
    ConsensusResult,
    CriticDecision,
    TradeIntent,
)
from packages.market_data.models import Candle, Timeframe


@dataclass
class DecisionResult:
    feature_snapshot: FeatureSnapshot
    market_regime: MarketRegime
    signals: List[AgentSignal]
    critic_decisions: List[CriticDecision]
    consensus: ConsensusResult
    allocation: AllocationDecision
    trade_intent: Optional[TradeIntent]
    strategy_config_hash: str
    reference_price: Decimal


class DecisionService:
    """Runtime orchestrator shared by paper trading and backtest."""

    def __init__(self) -> None:
        self.regime_agent = MarketRegimeAgent()
        self.trend_agent = TrendAgent()
        self.reversion_agent = MeanReversionAgent()
        self.breakout_agent = BreakoutAgent()

    async def decide(
        self,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        candles: List[Candle],
        as_of_time: datetime,
        reference_price: Decimal,
        feature_set: str = "standard_v1",
        strategy_config: StrategyConfig = default_strategy_config,
    ) -> DecisionResult:
        # 1. Features (strictly from candles with close_time <= as_of_time)
        req = FeatureComputationRequest(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            feature_set=feature_set,
            as_of_time=as_of_time,
        )
        from packages.features.pipeline import feature_pipeline  # local import avoids import cycles

        snapshot = feature_pipeline.compute(req, candles)

        # 2. Regime classification (real agent, from features)
        regime_ctx = AgentEvaluationContext(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            as_of_time=as_of_time,
            feature_snapshot=snapshot,
            market_regime=MarketRegime.UNKNOWN,
            data_quality_status="HEALTHY",
            reference_price=reference_price,
            strategy_config=strategy_config,
        )
        regime = self.regime_agent.classify_regime(regime_ctx)

        # 3. Alpha agents (real signals from features + real reference price)
        ctx = AgentEvaluationContext(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            as_of_time=as_of_time,
            feature_snapshot=snapshot,
            market_regime=regime,
            data_quality_status="HEALTHY",
            reference_price=reference_price,
            strategy_config=strategy_config,
        )
        signals: List[AgentSignal] = [
            await self.trend_agent.evaluate(ctx),
            await self.reversion_agent.evaluate(ctx),
            await self.breakout_agent.evaluate(ctx),
        ]

        # 4. Critic scrutiny
        critic_decisions = [critic_agent.review_signal(s, as_of_time) for s in signals]
        decisions_and_signals = list(zip(critic_decisions, signals, strict=True))

        # 5. Consensus
        consensus = signal_consensus_engine.evaluate_consensus(symbol, decisions_and_signals, as_of_time)

        # 6. Meta allocation -> TradeIntent or NO_TRADE
        allocation, intent = meta_allocator.evaluate_allocation(
            symbol=symbol,
            exchange=exchange,
            consensus=consensus,
            decisions=critic_decisions,
            signals=signals,
            market_regime=regime,
            current_time=as_of_time,
            strategy_config=strategy_config,
        )

        return DecisionResult(
            feature_snapshot=snapshot,
            market_regime=regime,
            signals=signals,
            critic_decisions=critic_decisions,
            consensus=consensus,
            allocation=allocation,
            trade_intent=intent,
            strategy_config_hash=strategy_config.config_hash,
            reference_price=reference_price,
        )


decision_service = DecisionService()
