from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from packages.execution.models import Fill, LiquidityType
from packages.persistence.unit_of_work import SqlAlchemyFillTxnOps
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager


class _Session:
    commit = AsyncMock()
    rollback = AsyncMock()


@pytest.mark.asyncio
async def test_durable_rollback_restores_in_memory_accounting() -> None:
    manager = PositionManager(
        "PAPER_ROLLBACK",
        PortfolioLedger(Decimal("10000"), "PAPER_ROLLBACK"),
    )
    ops = SqlAlchemyFillTxnOps(
        _Session(),  # type: ignore[arg-type]
        uuid4(),
        manager,
        initial_stop_price=Decimal("900"),
        take_profit_price=Decimal("1200"),
    )
    ops.ledger_repo.insert_entries = AsyncMock()
    ops.position_repo.upsert = AsyncMock()
    fill = Fill(
        fill_id=uuid4(),
        exchange_fill_id="PAPER_TEST",
        exchange_order_id=uuid4(),
        client_order_id=uuid4(),
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("1000"),
        quote_quantity=Decimal("1000"),
        fee=Decimal("1"),
        fee_asset="USDT",
        liquidity=LiquidityType.TAKER,
        executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    await ops.insert_ledger_entries(fill)
    await ops.upsert_position(fill)
    assert manager.ledger.cash_balance == Decimal("8999")
    assert manager.fill_history

    await ops.rollback()

    assert manager.ledger.cash_balance == Decimal("10000")
    assert manager.positions == {}
    assert manager.fill_history == []
    assert manager.ledger.processed_fill_ids == {}
