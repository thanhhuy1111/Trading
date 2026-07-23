from decimal import Decimal

from packages.schemas.execution import OrderSide
from packages.schemas.market import MarketTick
from packages.schemas.risk import RiskDecision
from packages.schemas.trade import TradeIntent


def test_market_tick_schema():
    tick = MarketTick(
        symbol="BTCUSDT",
        price=Decimal("65000.50"),
        quantity=Decimal("0.125"),
        exchange="binance_spot"
    )
    assert tick.symbol == "BTCUSDT"
    assert tick.price == Decimal("65000.50")
    assert tick.quantity == Decimal("0.125")


def test_trade_intent_schema():
    intent = TradeIntent(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        strategy_ids=["trend_momentum_v1"],
        expected_return_bps=45.0,
        confidence=0.82,
        entry_price_reference=Decimal("65000.0"),
        stop_price=Decimal("64000.0"),
        take_profit_price=Decimal("67000.0")
    )
    assert intent.symbol == "BTCUSDT"
    assert intent.side == OrderSide.BUY
    assert intent.confidence == 0.82
    assert intent.stop_price == Decimal("64000.0")


def test_risk_decision_schema():
    decision = RiskDecision(
        intent_id=TradeIntent(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            expected_return_bps=45.0,
            confidence=0.82,
            entry_price_reference=Decimal("65000.0"),
            stop_price=Decimal("64000.0"),
            take_profit_price=Decimal("67000.0")
        ).intent_id,
        approved=True,
        approved_quantity=Decimal("0.025"),
        approved_notional=Decimal("1625.0"),
        risk_amount=Decimal("250.0"),
        risk_percentage=0.0025
    )
    assert decision.approved is True
    assert decision.approved_quantity == Decimal("0.025")
    assert decision.risk_amount == Decimal("250.0")
