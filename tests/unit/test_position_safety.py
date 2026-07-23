from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.execution.models import Fill, LiquidityType
from packages.positions.exit_governor import exit_risk_validator
from packages.positions.exit_protector import ExitProtector
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager
from packages.positions.models import PositionExitIntent


def test_ledger_buy_and_sell_accounting_no_negative_balances() -> None:
    ledger = PortfolioLedger(initial_cash=Decimal("10000.00"))
    now = datetime.now(timezone.utc)

    buy_fill = Fill(
        fill_id=uuid4(),
        exchange_fill_id="FILL_BUY_001",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("0.1"),
        price=Decimal("50000.00"),
        quote_quantity=Decimal("5000.00"),
        fee=Decimal("5.00"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=now
    )

    entries, pnl = ledger.process_fill(buy_fill, now)
    assert ledger.cash_balance == Decimal("4995.00") # 10000 - 5000 - 5
    assert ledger.asset_balances["BTC"] == Decimal("0.1")

    # Reject fill if cash balance would become negative
    over_buy = buy_fill.model_copy(update={"fill_id": uuid4(), "quote_quantity": Decimal("10000.00")})
    with pytest.raises(ValueError, match="INSUFFICIENT_CASH"):
        ledger.process_fill(over_buy, now)


def test_position_manager_weighted_average_cost_basis() -> None:
    pm = PositionManager()
    now = datetime.now(timezone.utc)

    fill1 = Fill(
        fill_id=uuid4(),
        exchange_fill_id="F1",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("0.1"),
        price=Decimal("50000.00"),
        quote_quantity=Decimal("5000.00"),
        fee=Decimal("5.00"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=now
    )

    fill2 = Fill(
        fill_id=uuid4(),
        exchange_fill_id="F2",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("0.1"),
        price=Decimal("60000.00"),
        quote_quantity=Decimal("6000.00"),
        fee=Decimal("6.00"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=now
    )

    pos1, _ = pm.process_fill(fill1, now)
    assert pos1.average_entry_price == Decimal("50050.00") # 5005 / 0.1

    pos2, _ = pm.process_fill(fill2, now)
    # Total cost = 5005 + 6006 = 11011. Total Qty = 0.2. Avg = 55055.00
    assert pos2.average_entry_price == Decimal("55055.00")
    assert pos2.quantity == Decimal("0.2")


def test_exit_protector_trailing_stop_only_moves_upward() -> None:
    protector = ExitProtector(trailing_distance_pct=Decimal("0.02")) # 2% trailing
    pm = PositionManager()
    now = datetime.now(timezone.utc)

    fill = Fill(
        fill_id=uuid4(),
        exchange_fill_id="F1",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("0.1"),
        price=Decimal("50000.00"),
        quote_quantity=Decimal("5000.00"),
        fee=Decimal("5.00"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=now
    )
    pos, _ = pm.process_fill(fill, now)

    # Market rises to 60000 -> Trailing stop set to 60000 * 0.98 = 58800
    intent1, pos1 = protector.evaluate_position_exit(pos, Decimal("60000.00"), now)
    assert intent1 is None
    assert pos1.trailing_stop_price == Decimal("58800.00")

    # Market drops to 59000 -> Trailing stop stays at 58800 (never decreases!)
    intent2, pos2 = protector.evaluate_position_exit(pos1, Decimal("59000.00"), now)
    assert intent2 is None
    assert pos2.trailing_stop_price == Decimal("58800.00")

    # Market drops to 58000 (below 58800) -> Triggers trailing stop exit!
    intent3, pos3 = protector.evaluate_position_exit(pos2, Decimal("58000.00"), now)
    assert intent3 is not None
    assert intent3.trigger_type == "TRAILING_STOP"
    assert intent3.reduce_only is True


def test_exit_risk_validator_creates_reduce_only_sell_order() -> None:
    pm = PositionManager()
    now = datetime.now(timezone.utc)

    fill = Fill(
        fill_id=uuid4(),
        exchange_fill_id="F1",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("0.1"),
        price=Decimal("50000.00"),
        quote_quantity=Decimal("5000.00"),
        fee=Decimal("5.00"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=now
    )
    pos, _ = pm.process_fill(fill, now)

    intent = PositionExitIntent(
        position_id=pos.position_id,
        account_id=pos.account_id,
        exchange=pos.exchange,
        symbol=pos.symbol,
        side="SELL",
        reduce_only=True,
        requested_quantity=Decimal("0.1"),
        maximum_quantity=Decimal("0.1"),
        trigger_type="INITIAL_STOP",
        trigger_price=Decimal("49000.00"),
        reference_market_price=Decimal("49000.00"),
        minimum_exit_price=Decimal("48500.00"),
        maximum_slippage_bps=Decimal("10.0"),
        position_version=pos.version,
        generated_at=now,
        expires_at=now + timedelta(minutes=15)
    )

    approved, status = exit_risk_validator.validate_exit_intent(intent, now)
    assert status == "APPROVED"
    assert approved is not None
    assert approved.side == "SELL"
    assert approved.reduce_only is True
    assert approved.approved_quantity == Decimal("0.1")
