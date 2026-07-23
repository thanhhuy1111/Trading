from typing import Awaitable, Callable

from packages.common.logger import logger
from packages.events.envelope import DomainEventEnvelope
from packages.inbox.repository import InboxRepository


class IdempotentConsumerPipeline:
    """Wraps an event handler with database-backed inbox idempotency checks."""

    def __init__(self, consumer_name: str, session_factory):
        self.consumer_name = consumer_name
        self.session_factory = session_factory

    def wrap_handler(self, handler: Callable[[DomainEventEnvelope], Awaitable[None]]):
        async def _idempotent_handler(event: DomainEventEnvelope) -> None:
            async with self.session_factory() as session:
                repo = InboxRepository(session)

                # Step 1: Check if already processed
                if await repo.is_already_processed(event.event_id, self.consumer_name):
                    logger.info(
                        "Duplicate event skipped by inbox pipeline",
                        extra={"event_id": str(event.event_id), "consumer": self.consumer_name}
                    )
                    return

                # Step 2: Try claiming processing lock
                claimed = await repo.start_processing(event.event_id, self.consumer_name, event.event_type)
                await session.commit()

                if not claimed:
                    logger.info(
                        "Event already claimed by another consumer thread",
                        extra={"event_id": str(event.event_id), "consumer": self.consumer_name}
                    )
                    return

            # Step 3: Run the actual business handler
            try:
                await handler(event)
                async with self.session_factory() as session:
                    repo = InboxRepository(session)
                    await repo.mark_processed(event.event_id, self.consumer_name)
                    await session.commit()
            except Exception as e:
                logger.error(
                    "Idempotent consumer handler failed",
                    extra={"event_id": str(event.event_id), "consumer": self.consumer_name, "error": str(e)}
                )
                async with self.session_factory() as session:
                    repo = InboxRepository(session)
                    await repo.mark_failed(event.event_id, self.consumer_name, str(e))
                    await session.commit()
                raise e

        return _idempotent_handler
