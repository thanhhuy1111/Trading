from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.execution.adapter_interface import ExchangeExecutionAdapter
from packages.execution.models import (
    ExchangeOrder,
    ExchangeOrderRequest,
    ExchangeOrderResponse,
    ExchangeOrderStatus,
    ExecutionMode,
    Fill,
    LiquidityType,
)
from packages.paper.models import PaperLatencyConfig


class PaperExchangeAdapter(ExchangeExecutionAdapter):
    """Paper Exchange Execution Adapter simulating real-time paper execution without live exchange keys."""

    def __init__(self, latency_config: Optional[PaperLatencyConfig] = None) -> None:
        self.latency_config = latency_config or PaperLatencyConfig()
        self.submitted_orders: Dict[UUID, ExchangeOrder] = {}
        self.generated_fills: Dict[UUID, List[Fill]] = {}

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.PAPER

    async def submit_order(
        self,
        request: ExchangeOrderRequest,
    ) -> Tuple[ExchangeOrderResponse, List[Fill]]:
        # 1. Idempotency Check by client_order_id
        if request.client_order_id in self.submitted_orders:
            logger.info(
                "Paper order submission idempotent replay",
                extra={"client_order_id": str(request.client_order_id)}
            )
            existing_order = self.submitted_orders[request.client_order_id]
            existing_fills = self.generated_fills.get(request.client_order_id, [])
            res = ExchangeOrderResponse(
                client_order_id=request.client_order_id,
                exchange_order_id=existing_order.exchange_order_id,
                status=existing_order.status,
                acknowledged_at=existing_order.acknowledged_at or datetime.now(timezone.utc),
                message="Idempotent cached order response"
            )
            return res, existing_fills

        exchange_order_id = uuid4()
        now = datetime.now(timezone.utc)

        # 2. Realistic Fill Pricing (Slippage + Fee)
        slippage_factor = Decimal("1.0005") if request.side == "BUY" else Decimal("0.9995")
        fill_price = request.limit_price * slippage_factor
        fill_qty = request.quantity
        quote_qty = fill_qty * fill_price
        fee = quote_qty * Decimal("0.0010") # 10 bps fee

        fill = Fill(
            fill_id=uuid4(),
            exchange_fill_id=f"PAPER_FILL_{uuid4().hex[:8]}",
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
            executed_at=now
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
            filled_quantity=request.quantity,
            remaining_quantity=Decimal("0.0"),
            limit_price=request.limit_price,
            average_fill_price=fill_price,
            cumulative_quote_quantity=quote_qty,
            cumulative_fee=fee,
            status=ExchangeOrderStatus.FILLED,
            submitted_at=now,
            acknowledged_at=now,
            last_updated_at=now,
            expires_at=request.expires_at
        )

        self.submitted_orders[request.client_order_id] = order
        self.generated_fills[request.client_order_id] = [fill]

        response = ExchangeOrderResponse(
            client_order_id=request.client_order_id,
            exchange_order_id=exchange_order_id,
            status=ExchangeOrderStatus.FILLED,
            acknowledged_at=now,
            message="Paper order filled successfully"
        )

        logger.info(
            "Paper order executed",
            extra={"client_order_id": str(request.client_order_id), "symbol": request.symbol}
        )
        return response, [fill]

    async def cancel_order(self, client_order_id: UUID) -> bool:
        if client_order_id in self.submitted_orders:
            self.submitted_orders[client_order_id].status = ExchangeOrderStatus.CANCELLED
            return True
        return False

    async def get_order(self, client_order_id: UUID) -> Optional[ExchangeOrder]:
        return self.submitted_orders.get(client_order_id)
