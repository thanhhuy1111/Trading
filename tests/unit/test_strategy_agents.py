import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from packages.agents.models import AgentEvaluationContext, MarketRegime, SignalAction
from packages.agents.regime import MarketRegimeAgent
from packages.agents.trend import TrendAgent
from packages.features.models import FeatureSnapshot, Timeframe


def make_mock_snapshot(values: dict) -> FeatureSnapshot:
    now = datetime.now(timezone.utc)
    return FeatureSnapshot(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        feature_set="standard_v1",
        feature_set_version="1.0.0",
        event_time=now,
        as_of_time=now,
        computed_at=now,
        lookback_start=now,
        lookback_end=now,
        values=values,
        quality_status="VALID",
        quality_issues=[],
        source_data_version="v1",
        lineage={
            "source_exchange": "binance",
            "source_symbol": "BTC/USDT",
            "source_timeframe": "15m",
            "candle_count_used": 20,
            "oldest_candle_timestamp": now.isoformat(),
            "newest_candle_timestamp": now.isoformat(),
            "calculator_versions": {}
        }
    )


def test_market_regime_agent_uptrend_classification():
    snapshot = make_mock_snapshot({
        "adx_14": Decimal("30.0"), "ema_20_slope": Decimal("0.002"), "volatility_20": Decimal("0.01")
    })
    ctx = AgentEvaluationContext(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.M15, as_of_time=datetime.now(timezone.utc),
        feature_snapshot=snapshot, market_regime=MarketRegime.UNKNOWN, data_quality_status="HEALTHY"
    )
    agent = MarketRegimeAgent()
    regime = agent.classify_regime(ctx)
    assert regime == MarketRegime.TREND_UP


def test_trend_agent_generates_long_signal_in_uptrend():
    async def _test():
        snapshot = make_mock_snapshot({"adx_14": Decimal("30.0"), "ema_20_slope": Decimal("0.002")})
        ctx = AgentEvaluationContext(
            exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.M15, as_of_time=datetime.now(timezone.utc),
            feature_snapshot=snapshot, market_regime=MarketRegime.TREND_UP, data_quality_status="HEALTHY"
        )
        agent = TrendAgent()
        signal = await agent.evaluate(ctx)
        assert signal.action == SignalAction.LONG
        assert signal.confidence >= Decimal("0.70")
        assert "UPTREND_CONFIRMED" in signal.reason_codes
    asyncio.run(_test())
