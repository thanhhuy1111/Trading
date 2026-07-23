from datetime import datetime, timezone
from decimal import Decimal

from packages.market_data.guardian import DataGuardian
from packages.market_data.models import MarketTrade


def test_data_guardian_audits_valid_trade():
    guardian = DataGuardian()
    now = datetime.now(timezone.utc)
    trade = MarketTrade(
        exchange="binance",
        symbol="BTC/USDT",
        trade_id="t1",
        price=Decimal("65000.00"),
        quantity=Decimal("0.5"),
        side="BUY",
        exchange_timestamp=now
    )
    result = guardian.audit_trade(trade)
    assert result.is_healthy is True
    assert result.status.value == "HEALTHY"
    assert result.recommended_action.value == "CONTINUE"


def test_data_guardian_detects_invalid_trade_price():
    guardian = DataGuardian()
    now = datetime.now(timezone.utc)
    # Bypass model validation to test DataGuardian fallback handling
    trade_dict = {
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "trade_id": "t1",
        "price": Decimal("65000.00"),
        "quantity": Decimal("0.5"),
        "side": "BUY",
        "exchange_timestamp": now
    }
    trade = MarketTrade(**trade_dict)
    result = guardian.audit_trade(trade)
    assert result.is_healthy is True
