import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Tuple
from uuid import uuid4

from packages.common.logger import logger
from packages.execution.models import (
    ExchangeOrder,
    ExchangeOrderRequest,
    ExchangeOrderStatus,
    ExecutionMode,
    ExecutionReport,
    Fill,
    SimulatorOrderType,
    TimeInForce,
)
from packages.execution.planner import execution_planner
from packages.execution.simulator_adapter import simulator_exchange_adapter
from packages.execution.validator_gate import execution_validation_gate
from packages.risk.models import ApprovedOrder


class ExecutionEngine:
    """Core Execution Engine coordinating validation, planning, simulation, and report generation."""

    async def execute_approved_order(
        self,
        approved_order: ApprovedOrder,
        current_time: Optional[datetime] = None
    ) -> Tuple[ExecutionReport, List[Fill], Optional[ExchangeOrder]]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # 1. Pre-execution Validation Gate
        val_res = execution_validation_gate.validate_order(approved_order, current_time, ExecutionMode.SIMULATION)
        if not val_res.valid:
            logger.warning(
                "Execution validation failed",
                extra={
                    "approved_order_id": str(approved_order.approved_order_id),
                    "rejections": val_res.rejection_codes,
                }
            )
            report = ExecutionReport(
                approved_order_id=approved_order.approved_order_id,
                client_order_id=approved_order.client_order_id,
                final_status=ExchangeOrderStatus.BLOCKED,
                approved_quantity=approved_order.approved_quantity,
                submitted_quantity=Decimal("0.0"),
                filled_quantity=Decimal("0.0"),
                unfilled_quantity=approved_order.approved_quantity,
                maximum_notional=approved_order.maximum_notional,
                executed_notional=Decimal("0.0"),
                total_fee=Decimal("0.0"),
                average_fill_price=None,
                maximum_entry_price=approved_order.maximum_entry_price,
                child_order_ids=[],
                fill_ids=[],
                started_at=current_time,
                completed_at=current_time,
                report_fingerprint=hashlib.sha256(f"BLOCKED:{approved_order.approved_order_id}".encode("utf-8")).hexdigest()
            )
            return report, [], None

        # 2. Build Execution Plan
        plan = execution_planner.create_plan(approved_order, current_time)

        # 3. Create ExchangeOrderRequest
        child = plan.child_orders[0]
        order_req = ExchangeOrderRequest(
            approved_order_id=approved_order.approved_order_id,
            client_order_id=approved_order.client_order_id,
            exchange=approved_order.exchange,
            symbol=approved_order.symbol,
            side="BUY",
            order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
            time_in_force=TimeInForce.IOC,
            quantity=child.quantity,
            limit_price=child.limit_price,
            maximum_entry_price=approved_order.maximum_entry_price,
            remaining_approved_quantity=approved_order.approved_quantity,
            remaining_maximum_notional=approved_order.maximum_notional,
            submitted_at=current_time,
            expires_at=approved_order.expires_at
        )

        # 4. Submit to Simulator Exchange Adapter
        res, fills = await simulator_exchange_adapter.submit_order(order_req)
        sim_order = await simulator_exchange_adapter.get_order(approved_order.client_order_id)

        # 5. Build ExecutionReport
        filled_qty = sum((f.quantity for f in fills), Decimal("0.0"))
        executed_notional = sum((f.quote_quantity for f in fills), Decimal("0.0"))
        total_fee = sum((f.fee for f in fills), Decimal("0.0"))
        avg_price = (executed_notional / filled_qty) if filled_qty > Decimal("0.0") else None

        fp_src = (
            f"{approved_order.approved_order_id}:{approved_order.client_order_id}:"
            f"{res.status.value}:{filled_qty}"
        )
        report_fingerprint = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()

        report = ExecutionReport(
            approved_order_id=approved_order.approved_order_id,
            client_order_id=approved_order.client_order_id,
            final_status=res.status,
            approved_quantity=approved_order.approved_quantity,
            submitted_quantity=child.quantity,
            filled_quantity=filled_qty,
            unfilled_quantity=approved_order.approved_quantity - filled_qty,
            maximum_notional=approved_order.maximum_notional,
            executed_notional=executed_notional,
            total_fee=total_fee,
            average_fill_price=avg_price,
            maximum_entry_price=approved_order.maximum_entry_price,
            child_order_ids=[child.child_id],
            fill_ids=[f.fill_id for f in fills],
            started_at=current_time,
            completed_at=current_time,
            report_fingerprint=report_fingerprint
        )

        return report, fills, sim_order

    async def execute_approved_exit_order(
        self,
        approved_exit_order: Any,
        current_time: Optional[datetime] = None
    ) -> Tuple[ExecutionReport, List[Fill], Optional[ExchangeOrder]]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        child_id = uuid4()
        min_price = approved_exit_order.minimum_exit_price or Decimal("1.0")

        order_req = ExchangeOrderRequest(
            approved_order_id=approved_exit_order.approved_exit_order_id,
            client_order_id=approved_exit_order.client_order_id,
            exchange=approved_exit_order.exchange,
            symbol=approved_exit_order.symbol,
            side="SELL",
            order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
            time_in_force=TimeInForce.IOC,
            quantity=approved_exit_order.approved_quantity,
            limit_price=min_price,
            maximum_entry_price=Decimal("9999999.00"),
            remaining_approved_quantity=approved_exit_order.approved_quantity,
            remaining_maximum_notional=approved_exit_order.approved_quantity * min_price * Decimal("2.0"),
            submitted_at=current_time,
            expires_at=approved_exit_order.expires_at
        )

        res, fills = await simulator_exchange_adapter.submit_order(order_req)
        sim_order = await simulator_exchange_adapter.get_order(approved_exit_order.client_order_id)

        filled_qty = sum((f.quantity for f in fills), Decimal("0.0"))
        executed_notional = sum((f.quote_quantity for f in fills), Decimal("0.0"))
        total_fee = sum((f.fee for f in fills), Decimal("0.0"))
        avg_price = (executed_notional / filled_qty) if filled_qty > Decimal("0.0") else None

        fp_src = (
            f"EXIT:{approved_exit_order.approved_exit_order_id}:"
            f"{approved_exit_order.client_order_id}:{res.status.value}"
        )
        report_fingerprint = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()

        report = ExecutionReport(
            approved_order_id=approved_exit_order.approved_exit_order_id,
            client_order_id=approved_exit_order.client_order_id,
            final_status=res.status,
            approved_quantity=approved_exit_order.approved_quantity,
            submitted_quantity=approved_exit_order.approved_quantity,
            filled_quantity=filled_qty,
            unfilled_quantity=approved_exit_order.approved_quantity - filled_qty,
            maximum_notional=executed_notional,
            executed_notional=executed_notional,
            total_fee=total_fee,
            average_fill_price=avg_price,
            maximum_entry_price=min_price,
            child_order_ids=[child_id],
            fill_ids=[f.fill_id for f in fills],
            started_at=current_time,
            completed_at=current_time,
            report_fingerprint=report_fingerprint
        )

        return report, fills, sim_order


execution_engine = ExecutionEngine()
