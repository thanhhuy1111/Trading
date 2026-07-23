from datetime import datetime
from typing import List

from pydantic import BaseModel, Field

from packages.execution.models import ExecutionMode
from packages.risk.models import ApprovedOrder, RiskState
from packages.risk.state_machine import risk_state_machine


class ExecutionValidationCheck(BaseModel):
    check_name: str
    passed: bool
    explanation: str


class ExecutionValidationResult(BaseModel):
    valid: bool
    approved_order_id: str
    client_order_id: str
    checks: List[ExecutionValidationCheck] = Field(default_factory=list)
    rejection_codes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    validated_at: datetime
    validator_version: str = "1.0.0"


class ExecutionValidationGate:
    """Pre-execution validation gate for ApprovedOrder scrutinization."""

    def validate_order(
        self,
        order: ApprovedOrder,
        current_time: datetime,
        mode: ExecutionMode = ExecutionMode.SIMULATION
    ) -> ExecutionValidationResult:

        rejections = []
        checks = []

        # 1. Execution Mode Check
        if mode != ExecutionMode.SIMULATION:
            rejections.append("INVALID_EXECUTION_MODE")
            checks.append(ExecutionValidationCheck(
                check_name="ExecutionModeCheck",
                passed=False,
                explanation=f"Execution mode must be SIMULATION, got {mode.value}."
            ))

        # 2. Expiration Check
        if order.expires_at <= current_time:
            rejections.append("APPROVED_ORDER_EXPIRED")
            checks.append(ExecutionValidationCheck(
                check_name="OrderExpirationCheck",
                passed=False,
                explanation="ApprovedOrder expiration time has passed."
            ))

        # 3. Status Check
        if order.status != "PENDING_EXECUTION":
            rejections.append("INVALID_ORDER_STATUS")
            checks.append(ExecutionValidationCheck(
                check_name="OrderStatusCheck",
                passed=False,
                explanation=f"ApprovedOrder status must be PENDING_EXECUTION, got {order.status}."
            ))

        # 4. Global Risk State Check
        if risk_state_machine.state in [RiskState.HARD_STOP, RiskState.SOFT_STOP, RiskState.MANUAL_HALT]:
            rejections.append("GLOBAL_RISK_STATE_BLOCKED")
            checks.append(ExecutionValidationCheck(
                check_name="RiskStateCheck",
                passed=False,
                explanation=f"Global Risk State {risk_state_machine.state.value} blocks order execution."
            ))

        # 5. Price & Notional Bounds Check
        calc_notional = order.approved_quantity * order.maximum_entry_price
        if calc_notional > order.maximum_notional:
            rejections.append("MAXIMUM_NOTIONAL_EXCEEDED")
            checks.append(ExecutionValidationCheck(
                check_name="NotionalCapCheck",
                passed=False,
                explanation=f"Calculated notional ({calc_notional}) exceeds max ({order.maximum_notional})."
            ))

        is_valid = len(rejections) == 0
        return ExecutionValidationResult(
            valid=is_valid,
            approved_order_id=str(order.approved_order_id),
            client_order_id=str(order.client_order_id),
            checks=checks,
            rejection_codes=rejections,
            validated_at=current_time,
            validator_version="1.0.0"
        )


execution_validation_gate = ExecutionValidationGate()
