"""End-to-end Checkpoint 2 pipeline: raw candles -> validated candles -> features -> regime
-> strategy routing -> candidate.

This is the concrete proof the Master Plan's Checkpoint 2 completion condition asks for, and
the first piece of what Checkpoint 7 will eventually expose as the runtime recommendation
flow — built here as a plain function, not wired into any live/paper trading path yet.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

from packages.agents.regime import MarketRegimeAgent
from packages.agents.strategy_config import StrategyConfig, default_strategy_config
from packages.candidates.builder import build_proposed_candidate
from packages.candidates.models import TradeCandidate
from packages.governance.decision_service import decision_service
from packages.governance.strategy_router import RoutingDecision, route
from packages.market_data.historical_quality import DatasetQualityStatus, validate_historical_series
from packages.market_data.models import Candle, Timeframe

_regime_agent = MarketRegimeAgent()


@dataclass
class PipelineOutcome:
    candidate: Optional[TradeCandidate]
    regime_result: Optional[object]  # RegimeResult, kept loosely typed to avoid an import cycle
    routing_decision: Optional[RoutingDecision]
    rejected_reason: Optional[str] = None


async def run_candidate_pipeline(
    raw_candles: List[Candle],
    timeframe: Timeframe,
    as_of_time: datetime,
    symbol: str,
    exchange: str = "binance",
    strategy_config: StrategyConfig = default_strategy_config,
    session_id: Optional[UUID] = None,
    strategy_name: str = "checkpoint2_pipeline_demo",
    strategy_version: str = "1.0.0",
    now: Optional[datetime] = None,
    staleness_threshold: Optional[timedelta] = None,
) -> PipelineOutcome:
    """Runs the full chain for one decision point. Never fabricates a candidate: any rejection
    (bad data, stale data, no-trade regime, no signal) returns a PipelineOutcome with
    candidate=None and a reason, not a placeholder."""

    def _reject(reason: str, regime_result=None, routing_decision=None) -> PipelineOutcome:
        return PipelineOutcome(
            candidate=None, regime_result=regime_result, routing_decision=routing_decision, rejected_reason=reason,
        )

    # 1. Raw candles -> validated candles. Only candles with close_time<=as_of_time exist in
    # this "point in time" view — anything after is not passed in by the caller in the first
    # place, so there is nothing here that could leak future data into validation.
    clean_candles, quality_report = validate_historical_series(raw_candles, timeframe, as_of=as_of_time)
    if quality_report.status == DatasetQualityStatus.REJECTED:
        return _reject("DATASET_REJECTED_SEVERE_GAPS_OR_EMPTY")

    if not clean_candles or clean_candles[-1].close_time < as_of_time - _tolerance(timeframe):
        return _reject("NO_CANDLE_AT_DECISION_TIME")

    # 2. Staleness guard: refuse to generate a candidate from data that's too old relative to
    # "now" — a real runtime concern (Checkpoint 7), enforced here so it can never be skipped
    # by a caller that forgets to check freshness itself.
    if now is not None and staleness_threshold is not None:
        latest_close = clean_candles[-1].close_time
        if now - latest_close > staleness_threshold:
            return _reject("STALE_DATA")

    reference_price = clean_candles[-1].close_price

    # 3+4. Features + regime (both strictly from clean_candles with close_time<=as_of_time —
    # see FeaturePipeline.compute's own temporal filter and MarketRegimeAgent's point-in-time
    # test coverage in tests/unit/test_regime_detail.py).
    from packages.agents.models import AgentEvaluationContext, MarketRegime
    from packages.features.models import FeatureComputationRequest
    from packages.features.pipeline import feature_pipeline

    feature_req = FeatureComputationRequest(
        exchange=exchange, symbol=symbol, timeframe=timeframe, feature_set="standard_v1", as_of_time=as_of_time,
    )
    snapshot = feature_pipeline.compute(feature_req, clean_candles)
    regime_ctx = AgentEvaluationContext(
        exchange=exchange, symbol=symbol, timeframe=timeframe, as_of_time=as_of_time,
        feature_snapshot=snapshot, market_regime=MarketRegime.UNKNOWN, data_quality_status="HEALTHY",
        reference_price=reference_price, strategy_config=strategy_config,
    )
    regime_result = _regime_agent.classify_regime_detailed(regime_ctx)

    # 5. Strategy routing.
    routing_decision = route(regime_result.regime)
    if routing_decision.is_no_trade:
        return _reject("ROUTER_NO_TRADE", regime_result, routing_decision)

    # 6. Decision (only the routed agents run) -> candidate.
    decision = await decision_service.decide(
        exchange=exchange, symbol=symbol, timeframe=timeframe, candles=clean_candles,
        as_of_time=as_of_time, reference_price=reference_price, strategy_config=strategy_config,
        allowed_strategy_types=routing_decision.allowed_strategy_types,
    )

    if decision.trade_intent is None:
        return _reject("NO_TRADE_INTENT", regime_result, routing_decision)

    candidate = build_proposed_candidate(
        decision=decision, session_id=session_id or uuid4(),
        strategy_name=strategy_name, strategy_version=strategy_version,
    )
    return PipelineOutcome(candidate=candidate, regime_result=regime_result, routing_decision=routing_decision)


def _tolerance(timeframe: Timeframe) -> timedelta:
    from packages.market_data.historical_quality import TIMEFRAME_INTERVAL
    return TIMEFRAME_INTERVAL.get(timeframe, timedelta(days=1))
