from typing import List, Optional, Protocol, Tuple
from uuid import UUID

from packages.execution.models import (
    ExchangeOrder,
    ExchangeOrderRequest,
    ExchangeOrderResponse,
    ExecutionMode,
    Fill,
)


class ExchangeExecutionAdapter(Protocol):
    """Protocol for exchange order execution adapters."""

    @property
    def mode(self) -> ExecutionMode: ...

    async def submit_order(
        self,
        request: ExchangeOrderRequest,
    ) -> Tuple[ExchangeOrderResponse, List[Fill]]: ...

    async def cancel_order(
        self,
        client_order_id: UUID,
    ) -> bool: ...

    async def get_order(
        self,
        client_order_id: UUID,
    ) -> Optional[ExchangeOrder]: ...
