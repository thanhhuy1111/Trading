import hashlib
from datetime import datetime
from uuid import uuid4

from packages.execution.models import (
    ExecutionPlan,
    ExecutionTactic,
    PlannedChildOrder,
)
from packages.risk.models import ApprovedOrder


class ExecutionPlanner:
    """Plans child orders and execution tactics bounded by ApprovedOrder risk constraints."""

    def create_plan(
        self,
        order: ApprovedOrder,
        current_time: datetime,
        tactic: ExecutionTactic = ExecutionTactic.SINGLE_MARKETABLE_LIMIT
    ) -> ExecutionPlan:

        plan_id = uuid4()

        # Single marketable limit child order
        child = PlannedChildOrder(
            child_id=uuid4(),
            sequence=1,
            quantity=order.approved_quantity,
            limit_price=order.maximum_entry_price
        )

        fp_src = (
            f"{order.approved_order_id}:{order.client_order_id}:"
            f"{order.approved_quantity}:{order.risk_policy_version}"
        )
        plan_fingerprint = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()

        return ExecutionPlan(
            plan_id=plan_id,
            approved_order_id=order.approved_order_id,
            client_order_id=order.client_order_id,
            tactic=tactic,
            total_approved_quantity=order.approved_quantity,
            maximum_notional=order.maximum_notional,
            maximum_entry_price=order.maximum_entry_price,
            child_orders=[child],
            created_at=current_time,
            expires_at=order.expires_at,
            policy_version="1.0.0",
            plan_fingerprint=plan_fingerprint
        )


execution_planner = ExecutionPlanner()
