from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.events.envelope import DomainEventEnvelope
from packages.execution.models import Fill
from packages.outbox.repository import OutboxRepository
from packages.positions.manager import position_manager
from packages.positions.models import Position, RealizedPnlEntry


class PositionPipeline:
    """Orchestrates fill consumption, portfolio ledger, and Outbox event publishing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.outbox_repo = OutboxRepository(session)

    async def process_fill(
        self,
        fill: Fill,
        current_time: Optional[datetime] = None
    ) -> Tuple[Position, Optional[RealizedPnlEntry]]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        pos, pnl_entry = position_manager.process_fill(fill, current_time)

        # 1. Save Position projection
        await self._save_position(pos)

        # 2. Save Realized PnL Entry if exists
        if pnl_entry:
            await self._save_realized_pnl_entry(pnl_entry)

        # 3. Publish Outbox Events in SAME transaction
        evt_type = "position.closed" if pos.status == "CLOSED" else "position.opened"
        evt_pos = DomainEventEnvelope.create(
            event_type=evt_type,
            aggregate_type="position",
            aggregate_id=str(pos.position_id),
            payload=pos.model_dump(mode="json"),
            producer="position_manager"
        )
        await self.outbox_repo.save_event(evt_pos)

        snap = position_manager.get_portfolio_snapshot(current_time)
        evt_snap = DomainEventEnvelope.create(
            event_type="portfolio.snapshot_created",
            aggregate_type="portfolio_snapshot",
            aggregate_id=str(snap.snapshot_id),
            payload=snap.model_dump(mode="json"),
            producer="position_manager"
        )
        await self.outbox_repo.save_event(evt_snap)

        return pos, pnl_entry

    async def _save_position(self, pos: Position) -> None:
        query = text("""
            INSERT INTO positions (
                id, position_id, account_id, exchange, symbol, side, status, quantity,
                available_quantity, reserved_exit_quantity, average_entry_price, total_cost_basis,
                realized_pnl, unrealized_pnl, total_fees, current_market_price, market_value,
                initial_stop_price, active_stop_price, take_profit_price, trailing_stop_price,
                opened_at, last_fill_at, closed_at, version, schema_version
            ) VALUES (
                :id, :position_id, :account_id, :exchange, :symbol, :side, :status, :quantity,
                :available_quantity, :reserved_exit_quantity, :average_entry_price, :total_cost_basis,
                :realized_pnl, :unrealized_pnl, :total_fees, :current_market_price, :market_value,
                :initial_stop_price, :active_stop_price, :take_profit_price, :trailing_stop_price,
                :opened_at, :last_fill_at, :closed_at, :version, :schema_version
            ) ON CONFLICT (position_id) DO UPDATE SET
                status = EXCLUDED.status,
                quantity = EXCLUDED.quantity,
                available_quantity = EXCLUDED.available_quantity,
                reserved_exit_quantity = EXCLUDED.reserved_exit_quantity,
                average_entry_price = EXCLUDED.average_entry_price,
                total_cost_basis = EXCLUDED.total_cost_basis,
                realized_pnl = EXCLUDED.realized_pnl,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                total_fees = EXCLUDED.total_fees,
                current_market_price = EXCLUDED.current_market_price,
                market_value = EXCLUDED.market_value,
                active_stop_price = EXCLUDED.active_stop_price,
                trailing_stop_price = EXCLUDED.trailing_stop_price,
                last_fill_at = EXCLUDED.last_fill_at,
                closed_at = EXCLUDED.closed_at,
                version = EXCLUDED.version
        """)
        params = {
            "id": str(pos.position_id),
            "position_id": str(pos.position_id),
            "account_id": pos.account_id,
            "exchange": pos.exchange,
            "symbol": pos.symbol,
            "side": pos.side,
            "status": pos.status.value,
            "quantity": str(pos.quantity),
            "available_quantity": str(pos.available_quantity),
            "reserved_exit_quantity": str(pos.reserved_exit_quantity),
            "average_entry_price": str(pos.average_entry_price),
            "total_cost_basis": str(pos.total_cost_basis),
            "realized_pnl": str(pos.realized_pnl),
            "unrealized_pnl": str(pos.unrealized_pnl),
            "total_fees": str(pos.total_fees),
            "current_market_price": str(pos.current_market_price) if pos.current_market_price else None,
            "market_value": str(pos.market_value) if pos.market_value else None,
            "initial_stop_price": str(pos.initial_stop_price) if pos.initial_stop_price else None,
            "active_stop_price": str(pos.active_stop_price) if pos.active_stop_price else None,
            "take_profit_price": str(pos.take_profit_price) if pos.take_profit_price else None,
            "trailing_stop_price": str(pos.trailing_stop_price) if pos.trailing_stop_price else None,
            "opened_at": pos.opened_at,
            "last_fill_at": pos.last_fill_at,
            "closed_at": pos.closed_at,
            "version": pos.version,
            "schema_version": pos.schema_version,
        }
        await self.session.execute(query, params)

    async def _save_realized_pnl_entry(self, pnl: RealizedPnlEntry) -> None:
        query = text("""
            INSERT INTO realized_pnl_entries (
                id, pnl_entry_id, account_id, position_id, sell_fill_id, quantity, sale_proceeds,
                released_cost_basis, exit_fee, realized_pnl, realized_at, accounting_method, schema_version
            ) VALUES (
                :id, :pnl_entry_id, :account_id, :position_id, :sell_fill_id, :quantity, :sale_proceeds,
                :released_cost_basis, :exit_fee, :realized_pnl, :realized_at, :accounting_method, :schema_version
            ) ON CONFLICT (pnl_entry_id) DO NOTHING
        """)
        params = {
            "id": str(pnl.pnl_entry_id),
            "pnl_entry_id": str(pnl.pnl_entry_id),
            "account_id": pnl.account_id,
            "position_id": str(pnl.position_id),
            "sell_fill_id": str(pnl.sell_fill_id),
            "quantity": str(pnl.quantity),
            "sale_proceeds": str(pnl.sale_proceeds),
            "released_cost_basis": str(pnl.released_cost_basis),
            "exit_fee": str(pnl.exit_fee),
            "realized_pnl": str(pnl.realized_pnl),
            "realized_at": pnl.realized_at,
            "accounting_method": pnl.accounting_method,
            "schema_version": pnl.schema_version,
        }
        await self.session.execute(query, params)
