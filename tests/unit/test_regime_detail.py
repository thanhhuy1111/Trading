"""Checkpoint 2: regime classification must carry confidence/version/reason-code lineage and
must be strictly point-in-time (uses only context.as_of_time, no wall-clock leakage into the
classification itself)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import AgentEvaluationContext, MarketRegime
from packages.agents.regime import MarketRegimeAgent
from packages.features.models import FeatureComputationRequest

# Importing feature_pipeline registers all standard calculators as a side effect (see
# packages/features/pipeline.py) — do not re-register here, the registry rejects duplicates.
from packages.features.pipeline import feature_pipeline
from packages.market_data.models import Candle, Timeframe

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trending_candles(n: int = 60) -> list:
    candles = []
    price = Decimal("50000")
    for i in range(n):
        ct = T0 + timedelta(hours=i)
        step = price * Decimal("0.01")
        candles.append(Candle(
            exchange="binance", symbol="BTC/USDT", exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), trades_count=100, is_closed=True,
        ))
        price += step
    return candles


def _context_at(candles: list, as_of_time: datetime) -> AgentEvaluationContext:
    req = FeatureComputationRequest(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.H1,
        feature_set="standard_v1", as_of_time=as_of_time,
    )
    snapshot = feature_pipeline.compute(req, candles)
    return AgentEvaluationContext(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.H1, as_of_time=as_of_time,
        feature_snapshot=snapshot, market_regime=MarketRegime.UNKNOWN,
        data_quality_status="HEALTHY", reference_price=candles[-1].close_price,
    )


def test_regime_result_carries_full_lineage_metadata() -> None:
    agent = MarketRegimeAgent()
    candles = _trending_candles()
    ctx = _context_at(candles, candles[-1].close_time)
    result = agent.classify_regime_detailed(ctx)

    assert result.regime in list(MarketRegime)
    assert Decimal("0.0") <= result.confidence <= Decimal("1.0")
    assert result.regime_version == agent.version
    assert result.feature_timestamp == ctx.as_of_time
    assert len(result.reason_codes) > 0


def test_matches_classify_regime_exactly_single_source_of_truth() -> None:
    agent = MarketRegimeAgent()
    candles = _trending_candles()
    ctx = _context_at(candles, candles[-1].close_time)
    assert agent.classify_regime_detailed(ctx).regime == agent.classify_regime(ctx)


def test_unknown_regime_has_zero_confidence() -> None:
    agent = MarketRegimeAgent()
    # Too few candles for adx_14 (needs 28) -> UNKNOWN
    candles = _trending_candles(n=10)
    ctx = _context_at(candles, candles[-1].close_time)
    result = agent.classify_regime_detailed(ctx)
    assert result.regime == MarketRegime.UNKNOWN
    assert result.confidence == Decimal("0.0")
    assert "INSUFFICIENT_FEATURE_DATA" in result.reason_codes


def test_point_in_time_regime_is_invariant_to_future_candles() -> None:
    """Classifying at time T must give the identical result whether or not candles after T
    exist in the series passed in — the feature pipeline already enforces close_time<=as_of,
    and this proves classify_regime_detailed doesn't leak around that guarantee."""
    agent = MarketRegimeAgent()
    all_candles = _trending_candles(n=60)
    cutoff = all_candles[39].close_time

    candles_up_to_cutoff = [c for c in all_candles if c.close_time <= cutoff]
    result_a = agent.classify_regime_detailed(_context_at(candles_up_to_cutoff, cutoff))
    result_b = agent.classify_regime_detailed(_context_at(all_candles, cutoff))

    assert result_a.regime == result_b.regime
    assert result_a.confidence == result_b.confidence
    assert result_a.feature_timestamp == result_b.feature_timestamp == cutoff


def test_feature_timestamp_is_decision_time_not_wall_clock() -> None:
    agent = MarketRegimeAgent()
    candles = _trending_candles()
    historical_as_of = candles[-1].close_time  # a fixed point in the past, not "now"
    result = agent.classify_regime_detailed(_context_at(candles, historical_as_of))
    assert result.feature_timestamp == historical_as_of
    assert result.calculated_at != historical_as_of  # calculated_at is real wall-clock "now"
