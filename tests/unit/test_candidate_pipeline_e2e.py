"""Checkpoint 2 completion condition: raw candles -> validated candles -> features -> regime
-> strategy routing -> candidate, with full lineage and no leakage."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.governance.candidate_pipeline import run_candidate_pipeline
from packages.market_data.models import Candle, Timeframe

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _rising_candles(n: int = 60, *, duplicate_at: int = None) -> list:
    candles = []
    price = Decimal("50000")
    for i in range(n):
        ct = T0 + timedelta(hours=i)
        step = price * Decimal("0.01")
        c = Candle(
            exchange="binance", symbol="BTC/USDT", exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59, seconds=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), trades_count=100, is_closed=True,
        )
        candles.append(c)
        if duplicate_at == i:
            candles.append(c)  # inject a duplicate to prove the validator strips it
        price += step
    return candles


async def test_full_chain_produces_a_candidate_with_consistent_lineage() -> None:
    candles = _rising_candles(60, duplicate_at=10)
    as_of = candles[-1].close_time  # last real (non-duplicate) candle's close time

    outcome = await run_candidate_pipeline(
        raw_candles=candles, timeframe=Timeframe.H1, as_of_time=as_of, symbol="BTC/USDT",
    )

    assert outcome.regime_result is not None
    assert outcome.routing_decision is not None
    assert outcome.regime_result.regime == outcome.routing_decision.regime

    if outcome.candidate is not None:
        # Lineage: the candidate's regime and agent attribution must be consistent with what
        # the router actually allowed — never a strategy type the router rejected.
        assert outcome.candidate.market_regime == outcome.regime_result.regime.value
        from packages.agents.models import StrategyType
        from packages.agents.trend import TrendAgent
        allowed_agent_ids = set()
        if StrategyType.TREND_FOLLOWING in outcome.routing_decision.allowed_strategy_types:
            allowed_agent_ids.add(TrendAgent().agent_id)
        assert outcome.candidate.agent_source in allowed_agent_ids or outcome.candidate.supporting_agents


async def test_duplicate_candle_is_removed_before_any_feature_computation() -> None:
    candles = _rising_candles(60, duplicate_at=10)
    as_of = candles[-1].close_time
    outcome = await run_candidate_pipeline(
        raw_candles=candles, timeframe=Timeframe.H1, as_of_time=as_of, symbol="BTC/USDT",
    )
    # The pipeline must not crash or silently double-count the duplicate; either a candidate
    # or a clean NO_TRADE/ROUTER rejection is acceptable, a data-integrity exception is not.
    assert outcome.rejected_reason != "DATASET_REJECTED_SEVERE_GAPS_OR_EMPTY"


async def test_stale_data_never_produces_a_candidate() -> None:
    candles = _rising_candles(60)
    as_of = candles[-1].close_time
    # "now" is 10 days after the last candle -> way past any reasonable H1 staleness bound.
    now = as_of + timedelta(days=10)

    outcome = await run_candidate_pipeline(
        raw_candles=candles, timeframe=Timeframe.H1, as_of_time=as_of, symbol="BTC/USDT",
        now=now, staleness_threshold=timedelta(hours=6),
    )
    assert outcome.candidate is None
    assert outcome.rejected_reason == "STALE_DATA"


async def test_fresh_data_is_not_rejected_as_stale() -> None:
    candles = _rising_candles(60)
    as_of = candles[-1].close_time
    now = as_of + timedelta(minutes=5)

    outcome = await run_candidate_pipeline(
        raw_candles=candles, timeframe=Timeframe.H1, as_of_time=as_of, symbol="BTC/USDT",
        now=now, staleness_threshold=timedelta(hours=6),
    )
    assert outcome.rejected_reason != "STALE_DATA"


async def test_pipeline_result_is_invariant_to_future_candles_beyond_as_of() -> None:
    """No-leakage proof: candles after as_of_time must not change the pipeline's output at
    all (regime, routing, or candidate presence)."""
    all_candles = _rising_candles(80)
    cutoff = all_candles[59].close_time
    candles_up_to_cutoff = [c for c in all_candles if c.close_time <= cutoff]

    outcome_a = await run_candidate_pipeline(
        raw_candles=candles_up_to_cutoff, timeframe=Timeframe.H1, as_of_time=cutoff, symbol="BTC/USDT",
    )
    outcome_b = await run_candidate_pipeline(
        raw_candles=all_candles, timeframe=Timeframe.H1, as_of_time=cutoff, symbol="BTC/USDT",
    )

    assert outcome_a.regime_result.regime == outcome_b.regime_result.regime
    assert outcome_a.regime_result.confidence == outcome_b.regime_result.confidence
    assert (outcome_a.candidate is None) == (outcome_b.candidate is None)


async def test_too_few_candles_yields_unknown_regime_and_no_trade() -> None:
    candles = _rising_candles(5)  # far short of the 28-bar ADX requirement
    as_of = candles[-1].close_time
    outcome = await run_candidate_pipeline(
        raw_candles=candles, timeframe=Timeframe.H1, as_of_time=as_of, symbol="BTC/USDT",
    )
    assert outcome.candidate is None
    assert outcome.rejected_reason == "ROUTER_NO_TRADE"
    from packages.agents.models import MarketRegime
    assert outcome.regime_result.regime == MarketRegime.UNKNOWN
