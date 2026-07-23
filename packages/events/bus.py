from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from packages.events.envelope import DomainEventEnvelope


class PublishResult(BaseModel):
    """Result of publishing a domain event."""
    success: bool
    event_id: str
    topic: str
    partition: Optional[int] = None
    offset_or_message_id: Optional[str] = None
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_code: Optional[str] = None
    error_message: Optional[str] = None


EventHandler = Callable[[DomainEventEnvelope], Awaitable[None]]


class EventPublisher(Protocol):
    """Async interface for event publishing."""
    async def publish(self, event: DomainEventEnvelope) -> PublishResult:
        ...

    async def publish_batch(
        self,
        events: Sequence[DomainEventEnvelope]
    ) -> List[PublishResult]:
        ...


class EventConsumer(Protocol):
    """Async interface for event consumption."""
    async def subscribe(
        self,
        topic: str,
        group_id: str,
        handler: EventHandler
    ) -> None:
        ...

    async def stop(self) -> None:
        ...
