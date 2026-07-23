"""F-05: realized PnL is tracked in UTC-day / ISO-week buckets, not lifetime-cumulative."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from packages.execution.models import Fill, LiquidityType
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager


def _fill(side: str, price: Decimal, qty: Decimal, fee: Decimal, at: datetime) -> Fill:
    return Fill(
        fill_id=uuid4(),
        exchange_fill_id=f"F_{uuid4().hex[:6]}",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side=side,
        quantity=qty,
        price=price,
        quote_quantity=price * qty,
        fee=fee,
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=at,
    )


def _mgr() -> PositionManager:
    return PositionManager(account_id="PNL_WIN", ledger=PortfolioLedger(initial_cash=Decimal("100000.00")))


def test_yesterday_loss_does_not_count_towards_today() -> None:
    pm = _mgr()
    d1 = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    d2 = d1 + timedelta(days=1)

    pm.process_fill(_fill("BUY", Decimal("50000"), Decimal("0.1"), Decimal("5"), d1), d1)
    pm.process_fill(_fill("SELL", Decimal("49000"), Decimal("0.1"), Decimal("4.9"), d1), d1)

    # Day 1 realized PnL is negative and lives in day 1's bucket
    day1_pnl = pm.realized_pnl_window("DAILY", d1)
    assert day1_pnl < Decimal("0")
    # Day 2 starts fresh — yesterday's loss is NOT in today's daily bucket
    assert pm.realized_pnl_window("DAILY", d2) == Decimal("0.0")
    # But it remains inside the same ISO week
    assert pm.realized_pnl_window("WEEKLY", d1) == day1_pnl


def test_weekly_bucket_resets_next_iso_week() -> None:
    pm = _mgr()
    d1 = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)   # Thu, ISO week N
    next_week = d1 + timedelta(days=7)                        # next ISO week
    pm.process_fill(_fill("BUY", Decimal("50000"), Decimal("0.1"), Decimal("5"), d1), d1)
    pm.process_fill(_fill("SELL", Decimal("49000"), Decimal("0.1"), Decimal("4.9"), d1), d1)
    assert pm.realized_pnl_window("WEEKLY", d1) < Decimal("0")
    assert pm.realized_pnl_window("WEEKLY", next_week) == Decimal("0.0")


def test_late_fill_updates_the_correct_past_bucket() -> None:
    pm = _mgr()
    d1 = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    d3 = d1 + timedelta(days=2)
    # A fill whose event_time is day 1, processed "late" — must land in day 1's bucket
    pm.process_fill(_fill("BUY", Decimal("50000"), Decimal("0.1"), Decimal("5"), d1), d3)
    pm.process_fill(_fill("SELL", Decimal("51000"), Decimal("0.1"), Decimal("5.1"), d1), d3)
    assert pm.realized_pnl_window("DAILY", d1) > Decimal("0")   # profit booked to day 1
    assert pm.realized_pnl_window("DAILY", d3) == Decimal("0.0")


def test_timezone_of_event_does_not_shift_bucket() -> None:
    pm = _mgr()
    # 2026-07-23 23:30 in UTC-2 == 2026-07-24 01:30 UTC -> belongs to the 24th UTC day
    tz_minus2 = timezone(timedelta(hours=-2))
    t = datetime(2026, 7, 23, 23, 30, tzinfo=tz_minus2)
    pm.process_fill(_fill("BUY", Decimal("50000"), Decimal("0.1"), Decimal("5"), t), t)
    pm.process_fill(_fill("SELL", Decimal("51000"), Decimal("0.1"), Decimal("5.1"), t), t)
    utc_24 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    utc_23 = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    assert pm.realized_pnl_window("DAILY", utc_24) > Decimal("0")
    assert pm.realized_pnl_window("DAILY", utc_23) == Decimal("0.0")


def test_two_managers_have_independent_buckets() -> None:
    a = _mgr()
    b = _mgr()
    d1 = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    a.process_fill(_fill("BUY", Decimal("50000"), Decimal("0.1"), Decimal("5"), d1), d1)
    a.process_fill(_fill("SELL", Decimal("49000"), Decimal("0.1"), Decimal("4.9"), d1), d1)
    assert a.realized_pnl_window("DAILY", d1) < Decimal("0")
    assert b.realized_pnl_window("DAILY", d1) == Decimal("0.0")
