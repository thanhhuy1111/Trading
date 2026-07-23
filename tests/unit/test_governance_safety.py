from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from packages.agents.models import AgentSignal, MarketRegime, SignalAction, StrategyType
from packages.governance.allocator import meta_allocator
from packages.governance.consensus import signal_consensus_engine
from packages.governance.critic import critic_agent
from packages.governance.models import (
    AllocationResult,
    IntentSide,
    TradeIntent,
)
from packages.market_data.models import Timeframe


def test_trade_intent_has_no_quantity_or_execution_fields():
    """Safety Test: Proves TradeIntent schema strictly excludes execution fields."""
    intent = TradeIntent(
        symbol="BTC/USDT",
        exchange="binance",
        side=IntentSide.BUY,
        status="PENDING_RISK_REVIEW",
        strategy_ids=["trend_agent_v1"],
        source_signal_ids=[uuid4()],
        critic_decision_ids=[uuid4()],
        consensus_id=uuid4(),
        market_regime=MarketRegime.TREND_UP,
        expected_return_bps=Decimal("50.0"),
        weighted_confidence=Decimal("0.80"),
        estimated_fee_bps=Decimal("10.0"),
        estimated_spread_bps=Decimal("2.0"),
        estimated_slippage_bps=Decimal("5.0"),
        uncertainty_buffer_bps=Decimal("5.0"),
        net_edge_bps=Decimal("18.0"),
        reference_price=Decimal("65000.00"),
        horizon_minutes=60,
        feature_as_of_time=datetime.now(timezone.utc),
        generated_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=60)
    )

    forbidden_fields = [
        "quantity", "notional", "approved_notional", "leverage",
        "margin_mode", "order_type", "client_order_id"
    ]
    for f in forbidden_fields:
        assert not hasattr(intent, f), f"TradeIntent should NOT contain execution parameter '{f}'"


def test_critic_never_increases_confidence():
    """Safety Invariant: Proves CriticAgent never increases signal confidence."""
    now = datetime.now(timezone.utc)
    sig = AgentSignal(
        agent_id="test_agent",
        agent_name="Test Agent",
        agent_version="1.0.0",
        strategy_type=StrategyType.TREND_FOLLOWING,
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        action=SignalAction.LONG,
        confidence=Decimal("0.75"),
        horizon_minutes=60,
        reference_price=Decimal("65000.00"),
        market_regime=MarketRegime.TREND_UP,
        feature_snapshot_id=uuid4(),
        feature_set_version="1.0.0",
        feature_as_of_time=now,
        generated_at=now,
        expires_at=now + timedelta(minutes=60)
    )

    dec = critic_agent.review_signal(sig, now)
    assert dec.adjusted_confidence <= dec.original_confidence


def test_spot_short_signal_generates_no_trade():
    """Spot MVP Rule: Proves SHORT signal in Spot mode generates AllocationDecision (NO_TRADE)."""
    now = datetime.now(timezone.utc)
    sig = AgentSignal(
        agent_id="trend_agent_v1",
        agent_name="Trend Agent",
        agent_version="1.0.0",
        strategy_type=StrategyType.TREND_FOLLOWING,
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        action=SignalAction.SHORT,
        confidence=Decimal("0.85"),
        horizon_minutes=60,
        reference_price=Decimal("65000.00"),
        market_regime=MarketRegime.TREND_DOWN,
        feature_snapshot_id=uuid4(),
        feature_set_version="1.0.0",
        feature_as_of_time=now,
        generated_at=now,
        expires_at=now + timedelta(minutes=60)
    )

    dec = critic_agent.review_signal(sig, now)
    consensus = signal_consensus_engine.evaluate_consensus("BTC/USDT", [(dec, sig)], now)

    alloc_dec, intent = meta_allocator.evaluate_allocation(
        symbol="BTC/USDT",
        exchange="binance",
        consensus=consensus,
        decisions=[dec],
        signals=[sig],
        market_regime=MarketRegime.TREND_DOWN,
        current_time=now
    )

    assert alloc_dec.result == AllocationResult.NO_TRADE
    assert intent is None
    assert "SPOT_SHORT_NOT_EXECUTABLE" in alloc_dec.reason_codes
