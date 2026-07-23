from datetime import timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from packages.common.config import settings
from packages.schemas.execution import OrderSide
from packages.schemas.market import MarketTick
from packages.schemas.risk import RiskDecision
from packages.schemas.trade import TradeIntent


def test_invalid_endpoint_returns_404(client: TestClient):
    response = client.get("/invalid_endpoint_does_not_exist")
    assert response.status_code == 404


def test_live_trading_is_strictly_disabled_by_default():
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.FEATURE_FLAGS_LIVE_TRADING is False


def test_decimal_precision_validation():
    tick = MarketTick(
        symbol="BTCUSDT",
        price=Decimal("65432.10987654"),
        quantity=Decimal("1.23456789")
    )
    assert isinstance(tick.price, Decimal)
    assert isinstance(tick.quantity, Decimal)
    assert tick.price == Decimal("65432.10987654")


def test_trade_intent_has_no_quantity_field():
    intent = TradeIntent(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        expected_return_bps=30.0,
        confidence=0.75,
        entry_price_reference=Decimal("65000.0"),
        stop_price=Decimal("64000.0"),
        take_profit_price=Decimal("67000.0")
    )
    # TradeIntent MUST NOT have quantity attribute to prevent agents from bypass sizing
    assert not hasattr(intent, "quantity")
    assert not hasattr(intent, "approved_quantity")


def test_risk_decision_non_negative_quantity():
    decision = RiskDecision(
        intent_id=TradeIntent(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            expected_return_bps=30.0,
            confidence=0.75,
            entry_price_reference=Decimal("65000.0"),
            stop_price=Decimal("64000.0"),
            take_profit_price=Decimal("67000.0")
        ).intent_id,
        approved=True,
        approved_quantity=Decimal("0.05"),
        approved_notional=Decimal("3250.0")
    )
    assert decision.approved_quantity >= Decimal("0")


def test_utc_timestamp_validation():
    tick = MarketTick(
        symbol="ETHUSDT",
        price=Decimal("3500.0"),
        quantity=Decimal("2.0")
    )
    assert tick.timestamp.tzinfo is not None
    assert tick.timestamp.tzinfo == timezone.utc
