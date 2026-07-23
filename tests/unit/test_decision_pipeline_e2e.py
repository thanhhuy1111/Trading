"""End-to-end proof that the REAL multi-agent decision pipeline runs (F-01).

A closed-candle history flows through:
  FeaturePipeline -> MarketRegimeAgent -> {Trend, Reversion, Breakout} -> Critic
  -> Consensus -> MetaAllocator -> (TradeIntent | NO_TRADE)

with linked IDs and a strategy config hash. No fabricated intent is involved.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import MarketRegime
from packages.governance.decision_service import decision_service
from packages.governance.models import AllocationResult, ConsensusDirection, IntentSide
from packages.market_data.models import Candle, Timeframe


def _uptrend_candles(n: int, start: Decimal = Decimal("50000.00")) -> list[Candle]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = start
    for i in range(n):
        c_time = t0 + timedelta(hours=i)
        step = price * Decimal("0.005")  # steady +0.5% per bar
        open_p = price
        close_p = price + step
        candles.append(
            Candle(
                exchange="binance",
                symbol="BTC/USDT",
                exchange_timestamp=c_time,
                open_time=c_time,
                close_time=c_time + timedelta(minutes=59),
                timeframe=Timeframe.H1,
                open_price=open_p,
                high_price=close_p + Decimal("10"),
                low_price=open_p - Decimal("10"),
                close_price=close_p,
                volume=Decimal("100.00"),
                trades_count=1000,
                is_closed=True,
            )
        )
        price = close_p
    return candles


def test_full_decision_chain_produces_linked_trade_intent() -> None:
    candles = _uptrend_candles(40)
    last = candles[-1]

    result = asyncio.run(
        decision_service.decide(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            candles=candles,
            as_of_time=last.close_time,
            reference_price=last.close_price,
        )
    )

    # Every stage of the real chain executed
    assert result.feature_snapshot.values.get("ema_20_slope") is not None
    assert len(result.signals) == 3
    assert len(result.critic_decisions) == 3
    assert result.market_regime == MarketRegime.TREND_UP
    assert result.strategy_config_hash  # config hash recorded in lineage
    assert len(result.strategy_config_hash) == 64

    # Consensus is bullish and an intent is produced by the REAL allocator
    assert result.consensus.direction == ConsensusDirection.LONG
    assert result.trade_intent is not None
    intent = result.trade_intent
    assert intent.side == IntentSide.BUY
    assert intent.status == "PENDING_RISK_REVIEW"
    # Reference price comes from the live candle, never a hardcoded 65000
    assert intent.reference_price == last.close_price
    assert intent.reference_price != Decimal("65000.00")
    assert intent.net_edge_bps > Decimal("0")
    # Expected return is derived (not the old fabricated 50/150 constant)
    assert intent.expected_return_bps > Decimal("0")

    # Linked lineage IDs
    assert intent.consensus_id == result.consensus.consensus_id
    assert set(intent.critic_decision_ids) == {d.decision_id for d in result.critic_decisions}


def test_insufficient_warmup_produces_no_trade() -> None:
    candles = _uptrend_candles(5)  # far below feature warmup requirement
    last = candles[-1]

    result = asyncio.run(
        decision_service.decide(
            exchange="binance",
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            candles=candles,
            as_of_time=last.close_time,
            reference_price=last.close_price,
        )
    )

    assert result.market_regime == MarketRegime.UNKNOWN
    assert result.trade_intent is None
    assert result.allocation.result == AllocationResult.NO_TRADE


def test_critic_never_increases_confidence_in_chain() -> None:
    candles = _uptrend_candles(40)
    last = candles[-1]
    result = asyncio.run(
        decision_service.decide(
            exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.H1,
            candles=candles, as_of_time=last.close_time, reference_price=last.close_price,
        )
    )
    for dec in result.critic_decisions:
        assert dec.adjusted_confidence <= dec.original_confidence
