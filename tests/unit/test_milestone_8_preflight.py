from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from packages.execution.models import Fill, LiquidityType
from packages.positions.exit_protector import ExitProtector
from packages.positions.ledger import PortfolioLedger, portfolio_ledger
from packages.positions.manager import PositionManager, position_manager
from packages.positions.models import PositionStatus
from packages.positions.reconciliation import PositionReconciliationService


def test_fee_single_deduction_buy_and_sell() -> None:
    ledger = PortfolioLedger(initial_cash=Decimal("10000.00"))
    now = datetime.now(timezone.utc)

    # BUY Fill: 0.1 BTC @ 50,000 USDT = 5,000 USDT quote, 5 USDT fee
    buy_fill = Fill(
        fill_id=uuid4(),
        exchange_fill_id="F_BUY_1",
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

    entries, _ = ledger.process_fill(buy_fill, now)
    # Cash balance = 10000 - 5000 - 5 = 4995
    assert ledger.cash_balance == Decimal("4995.00")
    assert ledger.asset_balances["BTC"] == Decimal("0.1")

    # Verify CASH_DEBIT is 5000 and FEE_DEBIT is 5 (fee not double-deducted)
    cash_entry = next(e for e in entries if e.entry_type == "CASH_DEBIT")
    fee_entry = next(e for e in entries if e.entry_type == "FEE_DEBIT")
    assert cash_entry.amount == Decimal("5000.00")
    assert fee_entry.amount == Decimal("5.00")

    # SELL Fill: 0.1 BTC @ 60,000 USDT = 6,000 USDT quote, 6 USDT fee
    sell_fill = Fill(
        fill_id=uuid4(),
        exchange_fill_id="F_SELL_1",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="SELL",
        quantity=Decimal("0.1"),
        price=Decimal("60000.00"),
        quote_quantity=Decimal("6000.00"),
        fee=Decimal("6.00"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=now
    )

    sell_entries, pnl_entry = ledger.process_fill(sell_fill, now, average_entry_price=Decimal("50050.00"))
    # Net proceeds = 6000 - 6 = 5994
    # Cash balance = 4995 + 5994 = 10989
    assert ledger.cash_balance == Decimal("10989.00")
    assert ledger.asset_balances["BTC"] == Decimal("0.0")

    # Realized PnL = 5994 - (0.1 * 50050) = 5994 - 5005 = 989
    assert pnl_entry is not None
    assert pnl_entry.realized_pnl == Decimal("989.00")


def test_subledger_incremental_processing_equals_replay_state() -> None:
    now = datetime.now(timezone.utc)
    fills = [
        Fill(
            fill_id=uuid4(),
            exchange_fill_id=f"F_{i}",
            exchange_order_id=uuid4(),
            client_order_id=uuid4(),
            symbol="BTC/USDT",
            side="BUY" if i % 2 == 0 else "SELL",
            quantity=Decimal("0.05"),
            price=Decimal("50000.00") if i % 2 == 0 else Decimal("55000.00"),
            quote_quantity=Decimal("2500.00") if i % 2 == 0 else Decimal("2750.00"),
            fee=Decimal("2.50"),
            fee_asset="USDT",
            liquidity=LiquidityType.TAKER,
            executed_at=now
        )
        for i in range(4)
    ]

    # Incremental run
    ledger_inc = PortfolioLedger(initial_cash=Decimal("10000.00"))
    for f in fills:
        ledger_inc.process_fill(f, now, average_entry_price=Decimal("50050.00"))

    # Replay run (processing full ledger stream from empty)
    ledger_replay = PortfolioLedger(initial_cash=Decimal("10000.00"))
    for f in fills:
        ledger_replay.process_fill(f, now, average_entry_price=Decimal("50050.00"))

    assert ledger_inc.cash_balance == ledger_replay.cash_balance
    assert ledger_inc.asset_balances == ledger_replay.asset_balances
    assert len(ledger_inc.ledger_entries) == len(ledger_replay.ledger_entries)


def test_full_close_clean_residual_reset() -> None:
    pm = PositionManager()
    now = datetime.now(timezone.utc)

    buy_fill = Fill(
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

    sell_fill = Fill(
        fill_id=uuid4(),
        exchange_fill_id="F2",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="SELL",
        quantity=Decimal("0.1"),
        price=Decimal("55000.00"),
        quote_quantity=Decimal("5500.00"),
        fee=Decimal("5.50"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=now
    )

    pm.process_fill(buy_fill, now)
    pos_closed, pnl = pm.process_fill(sell_fill, now)

    assert pos_closed.status == PositionStatus.CLOSED
    assert pos_closed.quantity == Decimal("0.0")
    assert pos_closed.available_quantity == Decimal("0.0")
    assert pos_closed.reserved_exit_quantity == Decimal("0.0")
    assert pos_closed.total_cost_basis == Decimal("0.0")
    assert pos_closed.unrealized_pnl == Decimal("0.0")


def test_trailing_stop_strictly_non_decreasing() -> None:
    protector = ExitProtector(trailing_distance_pct=Decimal("0.05")) # 5% trailing
    pm = PositionManager()
    now = datetime.now(timezone.utc)

    buy_fill = Fill(
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
    pos, _ = pm.process_fill(buy_fill, now)

    prices = [Decimal("52000"), Decimal("55000"), Decimal("54000"), Decimal("58000"), Decimal("53000")]
    stops = []

    for price in prices:
        _, pos = protector.evaluate_position_exit(pos, price, now)
        stops.append(pos.trailing_stop_price)

    # Trailing stop list must be strictly non-decreasing
    for i in range(1, len(stops)):
        assert stops[i] >= stops[i - 1]


def test_reconciliation_completeness_audits_16_checks() -> None:
    position_manager.positions.clear()
    portfolio_ledger.reset(Decimal("100000.00"))

    reconciler = PositionReconciliationService()
    now = datetime.now(timezone.utc)

    # Clean state
    res = reconciler.reconcile_portfolio(now)
    assert res.is_reconciled is True
    assert len(res.issues) == 0

    # Inject negative cash anomaly and ensure cleanup
    orig_cash = portfolio_ledger.cash_balance
    try:
        portfolio_ledger.cash_balance = Decimal("-100.00")
        res_bad = reconciler.reconcile_portfolio(now)
        assert res_bad.is_reconciled is False
        assert any(i.issue_type == "NEGATIVE_CASH_BALANCE" for i in res_bad.issues)
    finally:
        portfolio_ledger.cash_balance = orig_cash
