import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.events.envelope import DomainEventEnvelope
from packages.execution.engine import execution_engine
from packages.execution.models import ExchangeOrder, ExecutionReport, Fill
from packages.outbox.repository import OutboxRepository
from packages.risk.models import ApprovedOrder


class ExecutionPipeline:
    """Orchestrates Execution Engine evaluation, PostgreSQL persistence, and Outbox event publishing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.outbox_repo = OutboxRepository(session)

    async def process_approved_order(
        self,
        approved_order: ApprovedOrder,
        current_time: Optional[datetime] = None
    ) -> Tuple[ExecutionReport, List[Fill], Optional[ExchangeOrder]]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        report, fills, sim_order = await execution_engine.execute_approved_order(approved_order, current_time)

        # 1. Save ExchangeOrder if exists
        if sim_order:
            await self._save_exchange_order(sim_order)

            # 2. Save Fills
            for f in fills:
                await self._save_fill(f)

        # 3. Save ExecutionReport
        await self._save_execution_report(report)

        # 4. Publish Outbox Events in SAME transaction
        evt_type = "order.filled" if report.final_status == "FILLED" else "order.submitted"
        evt_order = DomainEventEnvelope.create(
            event_type=evt_type,
            aggregate_type="exchange_order",
            aggregate_id=str(approved_order.client_order_id),
            payload=report.model_dump(mode="json"),
            producer="execution_engine"
        )
        await self.outbox_repo.save_event(evt_order)

        evt_report = DomainEventEnvelope.create(
            event_type="execution.report_created",
            aggregate_type="execution_report",
            aggregate_id=str(report.report_id),
            payload=report.model_dump(mode="json"),
            producer="execution_engine"
        )
        await self.outbox_repo.save_event(evt_report)

        return report, fills, sim_order

    async def _save_exchange_order(self, order: ExchangeOrder) -> None:
        query = text("""
            INSERT INTO exchange_orders (
                id, exchange_order_id, client_order_id, approved_order_id, exchange, symbol,
                side, order_type, time_in_force, original_quantity, filled_quantity, remaining_quantity,
                limit_price, average_fill_price, cumulative_quote_quantity, cumulative_fee, status,
                submitted_at, acknowledged_at, last_updated_at, expires_at, simulator_version,
                schema_version, created_at
            ) VALUES (
                :id, :exchange_order_id, :client_order_id, :approved_order_id, :exchange, :symbol,
                :side, :order_type, :time_in_force, :original_quantity, :filled_quantity, :remaining_quantity,
                :limit_price, :average_fill_price, :cumulative_quote_quantity, :cumulative_fee, :status,
                :submitted_at, :acknowledged_at, :last_updated_at, :expires_at, :simulator_version,
                :schema_version, NOW()
            ) ON CONFLICT (client_order_id) DO NOTHING
        """)
        params = {
            "id": str(order.exchange_order_id),
            "exchange_order_id": str(order.exchange_order_id),
            "client_order_id": str(order.client_order_id),
            "approved_order_id": str(order.approved_order_id),
            "exchange": order.exchange,
            "symbol": order.symbol,
            "side": order.side,
            "order_type": order.order_type.value,
            "time_in_force": order.time_in_force.value,
            "original_quantity": str(order.original_quantity),
            "filled_quantity": str(order.filled_quantity),
            "remaining_quantity": str(order.remaining_quantity),
            "limit_price": str(order.limit_price),
            "average_fill_price": str(order.average_fill_price) if order.average_fill_price else None,
            "cumulative_quote_quantity": str(order.cumulative_quote_quantity),
            "cumulative_fee": str(order.cumulative_fee),
            "status": order.status.value,
            "submitted_at": order.submitted_at,
            "acknowledged_at": order.acknowledged_at,
            "last_updated_at": order.last_updated_at,
            "expires_at": order.expires_at,
            "simulator_version": order.simulator_version,
            "schema_version": order.schema_version,
        }
        await self.session.execute(query, params)

    async def _save_fill(self, fill: Fill) -> None:
        query = text("""
            INSERT INTO fills (
                id, fill_id, exchange_fill_id, exchange_order_id, client_order_id, symbol,
                side, quantity, price, quote_quantity, fee, fee_asset, liquidity, executed_at,
                market_data_reference_id, simulator_version, schema_version
            ) VALUES (
                :id, :fill_id, :exchange_fill_id, :exchange_order_id, :client_order_id, :symbol,
                :side, :quantity, :price, :quote_quantity, :fee, :fee_asset, :liquidity, :executed_at,
                :market_data_reference_id, :simulator_version, :schema_version
            ) ON CONFLICT (fill_id) DO NOTHING
        """)
        params = {
            "id": str(fill.fill_id),
            "fill_id": str(fill.fill_id),
            "exchange_fill_id": fill.exchange_fill_id,
            "exchange_order_id": str(fill.exchange_order_id),
            "client_order_id": str(fill.client_order_id),
            "symbol": fill.symbol,
            "side": fill.side,
            "quantity": str(fill.quantity),
            "price": str(fill.price),
            "quote_quantity": str(fill.quote_quantity),
            "fee": str(fill.fee),
            "fee_asset": fill.fee_asset,
            "liquidity": fill.liquidity.value,
            "executed_at": fill.executed_at,
            "market_data_reference_id": str(fill.market_data_reference_id) if fill.market_data_reference_id else None,
            "simulator_version": fill.simulator_version,
            "schema_version": fill.schema_version,
        }
        await self.session.execute(query, params)

    async def _save_execution_report(self, rep: ExecutionReport) -> None:
        query = text("""
            INSERT INTO execution_reports (
                id, report_id, approved_order_id, client_order_id, final_status, approved_quantity,
                submitted_quantity, filled_quantity, unfilled_quantity, maximum_notional,
                executed_notional, total_fee, average_fill_price, maximum_entry_price, child_order_ids,
                fill_ids, started_at, completed_at, execution_policy_version, simulator_version,
                report_fingerprint, schema_version
            ) VALUES (
                :id, :report_id, :approved_order_id, :client_order_id, :final_status, :approved_quantity,
                :submitted_quantity, :filled_quantity, :unfilled_quantity, :maximum_notional,
                :executed_notional, :total_fee, :average_fill_price, :maximum_entry_price, :child_order_ids,
                :fill_ids, :started_at, :completed_at, :execution_policy_version, :simulator_version,
                :report_fingerprint, :schema_version
            ) ON CONFLICT (report_fingerprint) DO NOTHING
        """)
        params = {
            "id": str(rep.report_id),
            "report_id": str(rep.report_id),
            "approved_order_id": str(rep.approved_order_id),
            "client_order_id": str(rep.client_order_id),
            "final_status": rep.final_status.value,
            "approved_quantity": str(rep.approved_quantity),
            "submitted_quantity": str(rep.submitted_quantity),
            "filled_quantity": str(rep.filled_quantity),
            "unfilled_quantity": str(rep.unfilled_quantity),
            "maximum_notional": str(rep.maximum_notional),
            "executed_notional": str(rep.executed_notional),
            "total_fee": str(rep.total_fee),
            "average_fill_price": str(rep.average_fill_price) if rep.average_fill_price else None,
            "maximum_entry_price": str(rep.maximum_entry_price),
            "child_order_ids": json.dumps([str(c) for c in rep.child_order_ids]),
            "fill_ids": json.dumps([str(f) for f in rep.fill_ids]),
            "started_at": rep.started_at,
            "completed_at": rep.completed_at,
            "execution_policy_version": rep.execution_policy_version,
            "simulator_version": rep.simulator_version,
            "report_fingerprint": rep.report_fingerprint,
            "schema_version": rep.schema_version,
        }
        await self.session.execute(query, params)
