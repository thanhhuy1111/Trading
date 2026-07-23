from datetime import datetime, timezone
from typing import Optional, Tuple

from packages.common.logger import logger
from packages.positions.manager import position_manager
from packages.positions.models import ApprovedExitOrder, PositionExitIntent


class ExitRiskValidator:
    """Risk Governor extension validating PositionExitIntent and issuing ApprovedExitOrder."""

    def validate_exit_intent(
        self,
        intent: PositionExitIntent,
        current_time: Optional[datetime] = None
    ) -> Tuple[Optional[ApprovedExitOrder], str]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        pos = position_manager.positions.get(intent.symbol)
        if not pos or pos.status == "CLOSED":
            logger.error("Exit intent rejected: position closed or missing", extra={"symbol": intent.symbol})
            return None, "POSITION_CLOSED_OR_MISSING"

        if intent.requested_quantity > pos.available_quantity:
            logger.error(
                "Exit intent rejected: quantity exceeds available",
                extra={"requested": str(intent.requested_quantity), "available": str(pos.available_quantity)}
            )
            return None, "EXIT_QUANTITY_EXCEEDS_AVAILABLE"

        if not intent.reduce_only or intent.side != "SELL":
            logger.error(
                "Exit intent rejected: must be reduce_only SELL",
                extra={"side": intent.side, "reduce_only": intent.reduce_only}
            )
            return None, "INVALID_EXIT_SIDE_OR_REDUCE_ONLY"

        approved_order = ApprovedExitOrder(
            exit_intent_id=intent.exit_intent_id,
            position_id=intent.position_id,
            account_id=intent.account_id,
            exchange=intent.exchange,
            symbol=intent.symbol,
            side="SELL",
            reduce_only=True,
            approved_quantity=intent.requested_quantity,
            minimum_exit_price=intent.minimum_exit_price,
            maximum_slippage_bps=intent.maximum_slippage_bps,
            position_version=intent.position_version,
            expires_at=intent.expires_at,
            status="PENDING_EXECUTION"
        )

        return approved_order, "APPROVED"


exit_risk_validator = ExitRiskValidator()
