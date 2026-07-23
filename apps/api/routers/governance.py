from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from packages.agents.breakout import BreakoutAgent
from packages.agents.models import AgentEvaluationContext, MarketRegime
from packages.agents.regime import MarketRegimeAgent
from packages.agents.trend import TrendAgent
from packages.features.models import FeatureComputationRequest, Timeframe
from packages.features.pipeline import feature_pipeline
from packages.governance.allocator import meta_allocator
from packages.governance.consensus import signal_consensus_engine
from packages.governance.critic import critic_agent
from packages.market_data.adapters.binance import BinancePublicMarketDataProvider

router = APIRouter(tags=["Governance"])


@router.get("/critic/decisions")
async def list_critic_decisions(symbol: str = Query("BTC/USDT")) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    provider = BinancePublicMarketDataProvider()
    candles = await provider.fetch_candles(symbol, Timeframe.M15, now - (Timeframe.M15.value * 50), now, limit=50)

    req = FeatureComputationRequest(
        exchange="binance", symbol=symbol, timeframe=Timeframe.M15,
        feature_set="standard_v1", as_of_time=now
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
    breakout_sig = await BreakoutAgent().evaluate(eval_ctx)

    dec_trend = critic_agent.review_signal(trend_sig, now)
    dec_breakout = critic_agent.review_signal(breakout_sig, now)

    return [
        dec_trend.model_dump(mode="json"),
        dec_breakout.model_dump(mode="json")
    ]


@router.get("/trade-intents")
async def list_trade_intents(symbol: str = Query("BTC/USDT")) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    provider = BinancePublicMarketDataProvider()
    candles = await provider.fetch_candles(symbol, Timeframe.M15, now - (Timeframe.M15.value * 50), now, limit=50)

    req = FeatureComputationRequest(
        exchange="binance", symbol=symbol, timeframe=Timeframe.M15,
        feature_set="standard_v1", as_of_time=now
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
    breakout_sig = await BreakoutAgent().evaluate(eval_ctx)

    dec_trend = critic_agent.review_signal(trend_sig, now)
    dec_breakout = critic_agent.review_signal(breakout_sig, now)

    pairs = [(dec_trend, trend_sig), (dec_breakout, breakout_sig)]
    consensus = signal_consensus_engine.evaluate_consensus(symbol, pairs, now)

    alloc_dec, intent = meta_allocator.evaluate_allocation(
        symbol=symbol,
        exchange="binance",
        consensus=consensus,
        decisions=[dec_trend, dec_breakout],
        signals=[trend_sig, breakout_sig],
        market_regime=regime,
        current_time=now
    )

    if intent:
        return [intent.model_dump(mode="json")]
    return []
