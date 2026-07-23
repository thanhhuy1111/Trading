"""F-03 (in-memory): each session owns an isolated ledger; no cross-session mutation.

NOTE: this proves in-memory isolation only. Durable per-session persistence and
cross-process isolation require Postgres and are NOT verified here (see REMAINING_LIMITATIONS).
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from packages.execution.models import Fill, LiquidityType
from packages.paper.pipeline import PaperPipeline
from packages.paper.session import paper_session_manager
from packages.positions.exit_protector import ExitProtector
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager, position_manager


def _buy(symbol: str, at: datetime) -> Fill:
    return Fill(
        fill_id=uuid4(), exchange_fill_id=f"F_{uuid4().hex[:6]}", exchange_order_id=uuid4(),
        client_order_id=uuid4(), symbol=symbol, side="BUY", quantity=Decimal("0.1"),
        price=Decimal("50000"), quote_quantity=Decimal("5000"), fee=Decimal("5"),
        fee_asset="USDT", liquidity=LiquidityType.TAKER, executed_at=at,
    )


def test_two_sessions_have_independent_cash_and_positions() -> None:
    now = datetime.now(timezone.utc)
    a = PositionManager(account_id="A", ledger=PortfolioLedger(initial_cash=Decimal("10000.00")))
    b = PositionManager(account_id="B", ledger=PortfolioLedger(initial_cash=Decimal("5000.00")))

    a.process_fill(_buy("BTC/USDT", now), now)

    snap_a = a.get_portfolio_snapshot(now)
    snap_b = b.get_portfolio_snapshot(now)

    # A spent cash and holds a position; B is untouched
    assert snap_a.cash_balance == Decimal("4995.00")   # 10000 - 5000 - 5
    assert snap_b.cash_balance == Decimal("5000.00")
    assert "BTC/USDT" in a.positions
    assert "BTC/USDT" not in b.positions
    assert snap_a.nav != snap_b.nav
    # The global singleton ledger is not mutated by either session
    assert a.ledger is not b.ledger


def test_paper_pipeline_gives_each_session_its_own_ledger() -> None:
    sess_a = paper_session_manager.create_session("ISO_A", ["BTC/USDT"], ["1h"], initial_cash=Decimal("10000.00"))
    sess_b = paper_session_manager.create_session("ISO_B", ["ETH/USDT"], ["1h"], initial_cash=Decimal("5000.00"))
    pipe = PaperPipeline()
    pm_a = pipe.get_position_manager(sess_a.session_id)
    pm_b = pipe.get_position_manager(sess_b.session_id)

    assert pm_a.ledger is not pm_b.ledger
    assert pm_a.ledger.cash_balance == Decimal("10000.00")
    assert pm_b.ledger.cash_balance == Decimal("5000.00")


def test_exit_protector_writes_to_injected_manager_not_global() -> None:
    now = datetime.now(timezone.utc)
    pm = PositionManager(account_id="EXIT_ISO", ledger=PortfolioLedger(initial_cash=Decimal("10000.00")))
    pm.process_fill(_buy("ISO/TEST", now), now)
    pos = pm.positions["ISO/TEST"]

    protector = ExitProtector(trailing_distance_pct=Decimal("0.02"))
    protector.evaluate_position_exit(pos, Decimal("52000"), now, owner_position_manager=pm)

    # The session manager received the trailing-stop update; the global singleton did not.
    assert pm.positions["ISO/TEST"].trailing_stop_price is not None
    assert "ISO/TEST" not in position_manager.positions
