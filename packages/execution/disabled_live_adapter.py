from typing import List, Optional, Tuple
from uuid import UUID

from packages.execution.models import (
    ExchangeOrder,
    ExchangeOrderRequest,
    ExchangeOrderResponse,
    ExecutionMode,
    Fill,
)


class DisabledLiveExchangeAdapter:
    """Safety Adapter: Live trading is strictly disabled."""

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.LIVE

    async def submit_order(
        self,
        request: ExchangeOrderRequest,
    ) -> Tuple[ExchangeOrderResponse, List[Fill]]:
        raise RuntimeError("LIVE_EXECUTION_DISABLED: Real exchange order submission is strictly prohibited.")

    async def cancel_order(
        self,
        client_order_id: UUID,
    ) -> bool:
        raise RuntimeError("LIVE_EXECUTION_DISABLED: Real exchange cancellation is strictly prohibited.")

    async def get_order(
        self,
        client_order_id: UUID,
    ) -> Optional[ExchangeOrder]:
        raise RuntimeError("LIVE_EXECUTION_DISABLED: Real exchange query is strictly prohibited.")


disabled_live_adapter = DisabledLiveExchangeAdapter()
