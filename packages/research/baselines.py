"""Mandatory comparison baselines -- calling the REAL agent/DecisionService code, not a
re-implementation of their logic.

    NO_TRADE             never enters a position (the honest zero-cost, zero-risk baseline)
    BUY_AND_HOLD          always enters (the maximal-exposure baseline)
    TREND_ONLY            packages.agents.trend.TrendAgent's raw signal, no critic/consensus
    MEAN_REVERSION_ONLY   packages.agents.reversion.MeanReversionAgent's raw signal
    BREAKOUT_ONLY          packages.agents.breakout.BreakoutAgent's raw signal
    MULTI_AGENT_NO_ML     packages.governance.decision_service.decision_service.decide() --
                           the exact real agents -> critic -> consensus -> allocator chain
                           packages/recommendation/service.py drives in production. This IS
                           "the existing multi-agent system without ML": there has never
                           been any ML in that chain.

A model's expected_net_return_bps only means something relative to these -- comparing a
cost-aware model against cost-free or trivial baselines would be misleading, so every
baseline decision here is evaluated through the SAME cost-aware label table
(packages.research.labels), never a separate, more forgiving accounting.
"""

import asyncio
from datetime import datetime
from typing import Dict, List

import pandas as pd

from packages.agents.breakout import BreakoutAgent
from packages.agents.models import AgentEvaluationContext, MarketRegime, SignalAction
from packages.agents.regime import MarketRegimeAgent
from packages.agents.reversion import MeanReversionAgent
from packages.agents.strategy_config import default_strategy_config
from packages.agents.trend import TrendAgent
from packages.features.models import FeatureComputationRequest
from packages.features.pipeline import feature_pipeline
from packages.governance.decision_service import decision_service
from packages.market_data.models import Candle, Timeframe

BASELINE_NAMES = [
    "NO_TRADE", "BUY_AND_HOLD", "TREND_ONLY", "MEAN_REVERSION_ONLY", "BREAKOUT_ONLY", "MULTI_AGENT_NO_ML",
]

_regime_agent = MarketRegimeAgent()
_trend_agent = TrendAgent()
_reversion_agent = MeanReversionAgent()
_breakout_agent = BreakoutAgent()


def _build_context_and_regime(
    candles_window: List[Candle],
    exchange: str,
    symbol: str,
    timeframe: Timeframe,
    as_of_time: datetime,
    reference_price,
) -> AgentEvaluationContext:
    request = FeatureComputationRequest(
        exchange=exchange, symbol=symbol, timeframe=timeframe, feature_set="standard_v1", as_of_time=as_of_time
    )
    snapshot = feature_pipeline.compute(request, candles_window)
    probe_ctx = AgentEvaluationContext(
        exchange=exchange, symbol=symbol, timeframe=timeframe, as_of_time=as_of_time,
        feature_snapshot=snapshot, market_regime=MarketRegime.UNKNOWN, data_quality_status="HEALTHY",
        reference_price=reference_price, strategy_config=default_strategy_config,
    )
    regime = _regime_agent.classify_regime(probe_ctx)
    return AgentEvaluationContext(
        exchange=exchange, symbol=symbol, timeframe=timeframe, as_of_time=as_of_time,
        feature_snapshot=snapshot, market_regime=regime, data_quality_status="HEALTHY",
        reference_price=reference_price, strategy_config=default_strategy_config,
    )


async def _single_agent_long_decision(agent, ctx: AgentEvaluationContext) -> bool:
    signal = await agent.evaluate(ctx)
    return signal.action == SignalAction.LONG


async def _multi_agent_long_decision(
    candles_window: List[Candle],
    exchange: str,
    symbol: str,
    timeframe: Timeframe,
    as_of_time: datetime,
    reference_price,
) -> bool:
    result = await decision_service.decide(
        exchange=exchange, symbol=symbol, timeframe=timeframe,
        candles=candles_window, as_of_time=as_of_time, reference_price=reference_price,
    )
    return result.trade_intent is not None


async def compute_baseline_decisions(
    candles: List[Candle],
    entry_open_times: List[datetime],
    exchange: str,
    symbol: str,
    timeframe: Timeframe,
    lookback_window: int = 300,
) -> Dict[datetime, Dict[str, object]]:
    """Returns {entry_open_time: {baseline_name: decision, "market_regime": str}}. One
    decision per entry point (not per horizon) -- horizons share the same entry-time
    decision, computed once. `market_regime` is the SAME MarketRegimeAgent classification
    used to build each agent's context, exposed here so evaluation can break results down
    by regime without a second classification pass.
    """
    sorted_candles = sorted(candles, key=lambda c: c.open_time)
    index_by_open_time = {c.open_time: i for i, c in enumerate(sorted_candles)}

    decisions: Dict[datetime, Dict[str, object]] = {}
    for entry_open_time in entry_open_times:
        idx = index_by_open_time.get(entry_open_time)
        if idx is None:
            continue
        entry_candle = sorted_candles[idx]
        as_of_time = entry_candle.close_time
        reference_price = entry_candle.close_price
        window_start = max(0, idx + 1 - lookback_window)
        window = sorted_candles[window_start : idx + 1]

        ctx = _build_context_and_regime(window, exchange, symbol, timeframe, as_of_time, reference_price)

        trend_long = await _single_agent_long_decision(_trend_agent, ctx)
        reversion_long = await _single_agent_long_decision(_reversion_agent, ctx)
        breakout_long = await _single_agent_long_decision(_breakout_agent, ctx)
        multi_agent_long = await _multi_agent_long_decision(
            window, exchange, symbol, timeframe, as_of_time, reference_price
        )

        decisions[entry_open_time] = {
            "NO_TRADE": False,
            "BUY_AND_HOLD": True,
            "TREND_ONLY": trend_long,
            "MEAN_REVERSION_ONLY": reversion_long,
            "BREAKOUT_ONLY": breakout_long,
            "MULTI_AGENT_NO_ML": multi_agent_long,
            "market_regime": ctx.market_regime.value,
        }
    return decisions


def attach_baseline_decisions(
    label_table: pd.DataFrame,
    candles: List[Candle],
    exchange: str = "binance",
    lookback_window: int = 300,
) -> pd.DataFrame:
    """Adds one boolean `baseline__{NAME}` column per baseline, plus `market_regime`, to a
    COPY of label_table."""
    out = label_table.copy()
    for name in BASELINE_NAMES:
        out[f"baseline__{name}"] = False
    out["market_regime"] = None
    if out.empty:
        return out

    for (symbol, tf_value), group in out.groupby(["symbol", "timeframe"]):
        timeframe = Timeframe(tf_value)
        group_candles = [
            c for c in candles
            if c.symbol == symbol and (c.timeframe.value if hasattr(c.timeframe, "value") else c.timeframe) == tf_value
        ]
        entry_open_times = sorted(
            {t.to_pydatetime() if hasattr(t, "to_pydatetime") else t for t in group["entry_open_time"]}
        )
        decisions = asyncio.run(
            compute_baseline_decisions(group_candles, entry_open_times, exchange, symbol, timeframe, lookback_window)
        )
        for idx, row in group.iterrows():
            ot = row["entry_open_time"]
            ot = ot.to_pydatetime() if hasattr(ot, "to_pydatetime") else ot
            row_decisions = decisions.get(ot)
            if row_decisions is None:
                continue
            for name in BASELINE_NAMES:
                out.at[idx, f"baseline__{name}"] = row_decisions[name]
            out.at[idx, "market_regime"] = row_decisions["market_regime"]
    return out
