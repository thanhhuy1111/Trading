from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.execution.models import (
    ExchangeOrder,
    ExchangeOrderRequest,
    ExchangeOrderResponse,
    ExchangeOrderStatus,
    ExecutionMode,
    Fill,
    LiquidityType,
)


class SimulatorExchangeAdapter:
    """Deterministic Exchange Simulator Adapter for order execution."""

    def __init__(self, slippage_bps: Decimal = Decimal("5.0"), fee_bps: Decimal = Decimal("10.0")) -> None:
        self.slippage_bps = slippage_bps
        self.fee_bps = fee_bps
        self.orders: Dict[UUID, ExchangeOrder] = {}
        self.fills: Dict[UUID, List[Fill]] = {}

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.SIMULATION

    async def submit_order(
        self,
        request: ExchangeOrderRequest,
    ) -> Tuple[ExchangeOrderResponse, List[Fill]]:

        # Idempotency Check: Return existing order if duplicate client_order_id
        if request.client_order_id in self.orders:
            logger.info(
                "Idempotent submit_order request matched existing order",
                extra={"client_order_id": str(request.client_order_id)}
            )
            existing_order = self.orders[request.client_order_id]
            existing_fills = self.fills.get(request.client_order_id, [])
            res = ExchangeOrderResponse(
                client_order_id=request.client_order_id,
                exchange_order_id=existing_order.exchange_order_id,
                status=existing_order.status,
                acknowledged_at=existing_order.acknowledged_at or request.submitted_at,
                message="IDEMPOTENT_SUBMISSION_MATCH"
            )
            return res, existing_fills

        if request.side == "BUY":
            # Preflight 0.1: Market Reference Fill Price Formula for BUY
            best_ask = getattr(request, "best_ask", None) or request.limit_price
            if best_ask > request.limit_price:
                logger.info(
                    "Order unfilled: best_ask > limit_price",
                    extra={"best_ask": str(best_ask), "limit_price": str(request.limit_price)}
                )
                order = ExchangeOrder(
                    exchange_order_id=uuid4(),
                    client_order_id=request.client_order_id,
                    approved_order_id=request.approved_order_id,
                    exchange=request.exchange,
                    symbol=request.symbol,
                    side="BUY",
                    order_type=request.order_type,
                    time_in_force=request.time_in_force,
                    original_quantity=request.quantity,
                    filled_quantity=Decimal("0.0"),
                    remaining_quantity=request.quantity,
                    limit_price=request.limit_price,
                    average_fill_price=None,
                    cumulative_quote_quantity=Decimal("0.0"),
                    cumulative_fee=Decimal("0.0"),
                    status=ExchangeOrderStatus.REJECTED,
                    submitted_at=request.submitted_at,
                    acknowledged_at=request.submitted_at,
                    last_updated_at=request.submitted_at,
                    expires_at=request.expires_at,
                    simulator_version="1.0.0"
                )
                self.orders[request.client_order_id] = order
                self.fills[request.client_order_id] = []
                return ExchangeOrderResponse(
                    client_order_id=request.client_order_id,
                    exchange_order_id=order.exchange_order_id,
                    status=ExchangeOrderStatus.REJECTED,
                    acknowledged_at=request.submitted_at,
                    message="REJECTED_BEST_ASK_EXCEEDS_LIMIT"
                ), []

            raw_fill_price = best_ask * (Decimal("1.0") + (self.slippage_bps / Decimal("10000.0")))
            fill_price = min(raw_fill_price, request.limit_price, request.maximum_entry_price)
        else:
            # SELL side: best_bid reference
            best_bid = getattr(request, "best_bid", None) or request.limit_price
            raw_fill_price = best_bid * (Decimal("1.0") - (self.slippage_bps / Decimal("10000.0")))
            fill_price = max(raw_fill_price, request.limit_price)

        fill_qty = request.quantity
        quote_qty = fill_qty * fill_price
        fee = quote_qty * (self.fee_bps / Decimal("10000.0"))

        exchange_order_id = uuid4()
        fill_id = uuid4()

        fill = Fill(
            fill_id=fill_id,
            exchange_fill_id=f"SIM_FILL_{fill_id.hex[:8]}",
            exchange_order_id=exchange_order_id,
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=fill_qty,
            price=fill_price,
            quote_quantity=quote_qty,
            fee=fee,
            fee_asset="USDT",
            liquidity=LiquidityType.TAKER,
            executed_at=request.submitted_at,
            simulator_version="1.0.0"
        )

        order = ExchangeOrder(
            exchange_order_id=exchange_order_id,
            client_order_id=request.client_order_id,
            approved_order_id=request.approved_order_id,
            exchange=request.exchange,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            original_quantity=request.quantity,
            filled_quantity=fill_qty,
            remaining_quantity=Decimal("0.0"),
            limit_price=request.limit_price,
            average_fill_price=fill_price,
            cumulative_quote_quantity=quote_qty,
            cumulative_fee=fee,
            status=ExchangeOrderStatus.FILLED,
            submitted_at=request.submitted_at,
            acknowledged_at=request.submitted_at,
            last_updated_at=request.submitted_at,
            expires_at=request.expires_at,
            simulator_version="1.0.0"
        )

        self.orders[request.client_order_id] = order
        self.fills[request.client_order_id] = [fill]

        response = ExchangeOrderResponse(
            client_order_id=request.client_order_id,
            exchange_order_id=exchange_order_id,
            status=ExchangeOrderStatus.FILLED,
            acknowledged_at=request.submitted_at,
            message="ORDER_FILLED_SUCCESSFULLY"
        )

        return response, [fill]

    async def cancel_order(self, client_order_id: UUID) -> bool:
        if client_order_id in self.orders:
            order = self.orders[client_order_id]
            if order.status not in [ExchangeOrderStatus.FILLED, ExchangeOrderStatus.CANCELLED]:
                self.orders[client_order_id] = order.model_copy(update={"status": ExchangeOrderStatus.CANCELLED})
                return True
        return False

    async def get_order(self, client_order_id: UUID) -> Optional[ExchangeOrder]:
        return self.orders.get(client_order_id)


simulator_exchange_adapter = SimulatorExchangeAdapter()
