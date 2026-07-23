from datetime import datetime
from typing import Dict, List, Set
from uuid import UUID

from pydantic import BaseModel

from packages.common.logger import logger
from packages.execution.models import ExchangeOrderStatus


class OrderStateTransition(BaseModel):
    client_order_id: UUID
    previous_status: ExchangeOrderStatus
    new_status: ExchangeOrderStatus
    trigger: str
    reason_codes: List[str]
    actor: str = "OrderStateMachine"
    transitioned_at: datetime


class OrderStateMachine:
    """Validates and manages Order Status Transitions for Execution Engine."""

    VALID_TRANSITIONS: Dict[ExchangeOrderStatus, Set[ExchangeOrderStatus]] = {
        ExchangeOrderStatus.PENDING_EXECUTION: {ExchangeOrderStatus.VALIDATING},
        ExchangeOrderStatus.VALIDATING: {
            ExchangeOrderStatus.READY, ExchangeOrderStatus.BLOCKED,
            ExchangeOrderStatus.EXPIRED, ExchangeOrderStatus.REJECTED
        },
        ExchangeOrderStatus.READY: {ExchangeOrderStatus.SUBMISSION_PENDING},
        ExchangeOrderStatus.SUBMISSION_PENDING: {
            ExchangeOrderStatus.SUBMITTED, ExchangeOrderStatus.REJECTED,
            ExchangeOrderStatus.FAILED_RETRYABLE, ExchangeOrderStatus.UNKNOWN
        },
        ExchangeOrderStatus.SUBMITTED: {
            ExchangeOrderStatus.ACKNOWLEDGED, ExchangeOrderStatus.PARTIALLY_FILLED,
            ExchangeOrderStatus.FILLED, ExchangeOrderStatus.CANCEL_PENDING,
            ExchangeOrderStatus.EXPIRED, ExchangeOrderStatus.UNKNOWN
        },
        ExchangeOrderStatus.ACKNOWLEDGED: {
            ExchangeOrderStatus.PARTIALLY_FILLED, ExchangeOrderStatus.FILLED,
            ExchangeOrderStatus.CANCEL_PENDING, ExchangeOrderStatus.EXPIRED
        },
        ExchangeOrderStatus.PARTIALLY_FILLED: {
            ExchangeOrderStatus.PARTIALLY_FILLED, ExchangeOrderStatus.FILLED,
            ExchangeOrderStatus.CANCEL_PENDING, ExchangeOrderStatus.CANCELLED,
            ExchangeOrderStatus.EXPIRED
        },
        ExchangeOrderStatus.CANCEL_PENDING: {
            ExchangeOrderStatus.CANCELLED, ExchangeOrderStatus.FILLED,
            ExchangeOrderStatus.PARTIALLY_FILLED, ExchangeOrderStatus.UNKNOWN
        },
        ExchangeOrderStatus.FAILED_RETRYABLE: {
            ExchangeOrderStatus.SUBMISSION_PENDING, ExchangeOrderStatus.FAILED_FINAL
        },
        ExchangeOrderStatus.UNKNOWN: {
            ExchangeOrderStatus.ACKNOWLEDGED, ExchangeOrderStatus.PARTIALLY_FILLED,
            ExchangeOrderStatus.FILLED, ExchangeOrderStatus.CANCELLED,
            ExchangeOrderStatus.REJECTED, ExchangeOrderStatus.FAILED_FINAL
        }
    }

    def validate_transition(
        self,
        current_status: ExchangeOrderStatus,
        new_status: ExchangeOrderStatus,
        client_order_id: UUID,
        trigger: str,
        reason_codes: List[str],
        current_time: datetime
    ) -> OrderStateTransition:

        allowed = self.VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            logger.error("Invalid Order State Transition Attempted", extra={
                "client_order_id": str(client_order_id),
                "current_status": current_status.value,
                "new_status": new_status.value
            })
            raise ValueError(f"Invalid Order State Transition: {current_status.value} -> {new_status.value}")

        return OrderStateTransition(
            client_order_id=client_order_id,
            previous_status=current_status,
            new_status=new_status,
            trigger=trigger,
            reason_codes=reason_codes,
            actor="ExecutionEngine",
            transitioned_at=current_time
        )


order_state_machine = OrderStateMachine()
