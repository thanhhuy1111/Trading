from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Optional, Tuple
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.positions.manager import position_manager
from packages.positions.models import (
    ExitTriggerType,
    Position,
    PositionExitIntent,
)


class ExitProtector:
    """Monitors positions for Stop-Loss, Take-Profit, and Trailing-Stop triggers, generating PositionExitIntent."""

    def __init__(self, trailing_distance_pct: Decimal = Decimal("0.02")) -> None:
        self.trailing_distance_pct = trailing_distance_pct
        self.highest_prices: Dict[UUID, Decimal] = {}

    def evaluate_position_exit(
        self,
        position: Position,
        current_market_price: Decimal,
        current_time: Optional[datetime] = None,
        owner_position_manager: Optional[object] = None
    ) -> Tuple[Optional[PositionExitIntent], Position]:

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # F-03: write trailing-stop state to the caller's session-scoped manager when provided,
        # falling back to the module singleton only for legacy callers.
        target_manager = owner_position_manager if owner_position_manager is not None else position_manager

        if position.status == "CLOSED" or position.available_quantity <= Decimal("0.0"):
            return None, position

        # Update highest price for trailing stop
        prev_high = self.highest_prices.get(position.position_id, position.average_entry_price)
        new_high = max(prev_high, current_market_price)
        self.highest_prices[position.position_id] = new_high

        # Calculate candidate trailing stop
        candidate_trailing = new_high * (Decimal("1.0") - self.trailing_distance_pct)
        default_stop = position.average_entry_price * Decimal("0.95")
        active_stop = position.active_stop_price or position.initial_stop_price or default_stop
        had_trailing_stop = position.trailing_stop_price is not None
        new_trailing_stop = max(position.trailing_stop_price or Decimal("0.0"), candidate_trailing, active_stop)

        # Update position's trailing stop
        position = position.model_copy(update={
            "trailing_stop_price": new_trailing_stop,
            "current_market_price": current_market_price,
        })
        target_manager.positions[position.symbol] = position

        trigger_type: Optional[ExitTriggerType] = None
        trigger_price = current_market_price

        # 1. Stop-Loss Trigger (Fixed or Trailing)
        if current_market_price <= new_trailing_stop:
            is_trail = had_trailing_stop or current_market_price > active_stop
            trigger_type = ExitTriggerType.TRAILING_STOP if is_trail else ExitTriggerType.INITIAL_STOP
            trigger_price = new_trailing_stop
            logger.warning(
                "Stop-Loss trigger reached",
                extra={"symbol": position.symbol, "market_price": str(current_market_price)}
            )

        # 2. Take-Profit Trigger
        elif position.take_profit_price and current_market_price >= position.take_profit_price:
            trigger_type = ExitTriggerType.TAKE_PROFIT
            trigger_price = position.take_profit_price
            logger.info(
                "Take-Profit trigger reached",
                extra={"symbol": position.symbol, "market_price": str(current_market_price)}
            )

        if trigger_type:
            intent = PositionExitIntent(
                position_id=position.position_id,
                account_id=position.account_id,
                exchange=position.exchange,
                symbol=position.symbol,
                side="SELL",
                reduce_only=True,
                requested_quantity=position.available_quantity,
                maximum_quantity=position.available_quantity,
                trigger_type=trigger_type,
                trigger_price=trigger_price,
                reference_market_price=current_market_price,
                minimum_exit_price=trigger_price * Decimal("0.99"),
                maximum_slippage_bps=Decimal("10.0"),
                position_version=position.version,
                market_data_reference_id=uuid4(),
                generated_at=current_time,
                expires_at=current_time + timedelta(minutes=15)
            )
            return intent, position

        return None, position


exit_protector = ExitProtector()
