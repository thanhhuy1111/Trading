from typing import Dict, List, Sequence

from packages.events.bus import EventHandler, PublishResult
from packages.events.envelope import DomainEventEnvelope


class InMemoryEventBus:
    """In-Memory Event Bus adapter for unit testing."""

    def __init__(self):
        self.published_events: List[DomainEventEnvelope] = []
        self._handlers: Dict[str, List[EventHandler]] = {}

    async def publish(self, event: DomainEventEnvelope) -> PublishResult:
        self.published_events.append(event)
        
        # Dispatch to subscribed handlers
        topic = f"trading.event.{event.event_type}"
        handlers = self._handlers.get(topic, []) + self._handlers.get(event.event_type, [])
        
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                return PublishResult(
                    success=False,
                    event_id=str(event.event_id),
                    topic=topic,
                    error_code="HANDLER_ERROR",
                    error_message=str(e)
                )

        return PublishResult(
            success=True,
            event_id=str(event.event_id),
            topic=topic,
            offset_or_message_id=str(len(self.published_events))
        )

    async def publish_batch(
        self,
        events: Sequence[DomainEventEnvelope]
    ) -> List[PublishResult]:
        results = []
        for event in events:
            res = await self.publish(event)
            results.append(res)
        return results

    async def subscribe(
        self,
        topic: str,
        group_id: str,
        handler: EventHandler
    ) -> None:
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)

    async def stop(self) -> None:
        self.published_events.clear()
        self._handlers.clear()
