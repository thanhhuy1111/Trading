from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from packages.agents.breakout import BreakoutAgent
from packages.agents.models import AgentEvaluationContext, MarketRegime
from packages.agents.regime import MarketRegimeAgent
from packages.agents.reversion import MeanReversionAgent
from packages.agents.trend import TrendAgent
from packages.features.models import FeatureComputationRequest, Timeframe
from packages.features.pipeline import feature_pipeline
from packages.market_data.adapters.binance import BinancePublicMarketDataProvider

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.get("")
async def list_agents() -> List[Dict[str, Any]]:
    return [
        {
            "agent_id": "regime_agent_v1",
            "name": "Market Regime Agent",
            "version": "1.0.0",
            "strategy_type": "REGIME_CLASSIFIER",
            "status": "ACTIVE",
            "circuit_breaker": "CLOSED",
            "trading_permission": "NONE (Analysis Only)"
        },
        {
            "agent_id": "trend_agent_v1",
            "name": "Trend Following Agent",
            "version": "1.0.0",
            "strategy_type": "TREND_FOLLOWING",
            "status": "ACTIVE",
            "circuit_breaker": "CLOSED",
            "trading_permission": "NONE (Analysis Only)"
        },
        {
            "agent_id": "reversion_agent_v1",
            "name": "Mean Reversion Agent",
            "version": "1.0.0",
            "strategy_type": "MEAN_REVERSION",
            "status": "ACTIVE",
            "circuit_breaker": "CLOSED",
            "trading_permission": "NONE (Analysis Only)"
        },
        {
            "agent_id": "breakout_agent_v1",
            "name": "Breakout Strategy Agent",
            "version": "1.0.0",
            "strategy_type": "BREAKOUT",
            "status": "ACTIVE",
            "circuit_breaker": "CLOSED",
            "trading_permission": "NONE (Analysis Only)"
        }
    ]


@router.get("/signals")
async def list_signals(
    symbol: str = Query("BTC/USDT"),
    limit: int = 10
) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    provider = BinancePublicMarketDataProvider()
    candles = await provider.fetch_candles(symbol, Timeframe.M15, now - (Timeframe.M15.value * 50), now, limit=50)

    req = FeatureComputationRequest(
        exchange="binance",
        symbol=symbol,
        timeframe=Timeframe.M15,
        feature_set="standard_v1",
        as_of_time=now
    )
    snapshot = feature_pipeline.compute(req, candles)

    regime_agent = MarketRegimeAgent()
    regime = regime_agent.classify_regime(
        AgentEvaluationContext(
            exchange="binance", symbol=symbol, timeframe=Timeframe.M15, as_of_time=now,
            feature_snapshot=snapshot, market_regime=MarketRegime.UNKNOWN, data_quality_status="HEALTHY"
        )
    )

    eval_ctx = AgentEvaluationContext(
        exchange="binance", symbol=symbol, timeframe=Timeframe.M15, as_of_time=now,
        feature_snapshot=snapshot, market_regime=regime, data_quality_status="HEALTHY"
    )

    trend_sig = await TrendAgent().evaluate(eval_ctx)
    reversion_sig = await MeanReversionAgent().evaluate(eval_ctx)
    breakout_sig = await BreakoutAgent().evaluate(eval_ctx)

    return [
        trend_sig.model_dump(mode="json"),
        reversion_sig.model_dump(mode="json"),
        breakout_sig.model_dump(mode="json")
    ]
