import asyncio
import json
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.logger import logger
from packages.events.bus import EventPublisher
from packages.events.envelope import DomainEventEnvelope, EventMetadata
from packages.outbox.repository import OutboxRepository


class OutboxPublisherWorker:
    """Async background worker polling outbox events and publishing to Event Bus."""

    def __init__(
        self,
        event_bus: EventPublisher,
        worker_id: Optional[str] = None,
        poll_interval: float = 1.0,
        batch_size: int = 50
    ):
        self.event_bus = event_bus
        self.worker_id = worker_id or f"outbox_worker_{str(uuid4())[:8]}"
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self._running = False
        self._processed_count = 0
        self._failed_count = 0

    @property
    def metrics(self):
        return {
            "worker_id": self.worker_id,
            "processed_count": self._processed_count,
            "failed_count": self._failed_count,
            "is_running": self._running
        }

    async def process_batch(self, session: AsyncSession) -> int:
        repo = OutboxRepository(session)
        events_batch = await repo.fetch_and_lock_pending(self.worker_id, self.batch_size)
        
        if not events_batch:
            return 0

        for row in events_batch:
            try:
                payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                meta_dict = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

                envelope = DomainEventEnvelope(
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    aggregate_type=row["aggregate_type"],
                    aggregate_id=row["aggregate_id"],
                    schema_version=row["schema_version"],
                    payload=payload,
                    metadata=EventMetadata(**meta_dict)
                )

                result = await self.event_bus.publish(envelope)
                if result.success:
                    await repo.mark_published(row["id"])
                    self._processed_count += 1
                else:
                    await repo.mark_failed(row["id"], result.error_message or "Bus publish failed")
                    self._failed_count += 1
            except Exception as e:
                logger.error("Outbox worker error processing row", extra={"id": str(row["id"]), "error": str(e)})
                await repo.mark_failed(row["id"], str(e))
                self._failed_count += 1

        await session.commit()
        return len(events_batch)

    async def run_loop(self, session_factory):
        self._running = True
        logger.info("OutboxPublisherWorker loop started", extra={"worker_id": self.worker_id})
        while self._running:
            try:
                async with session_factory() as session:
                    count = await self.process_batch(session)
                    if count == 0:
                        await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("OutboxPublisherWorker unhandled error", extra={"error": str(e)})
                await asyncio.sleep(self.poll_interval)

    def stop(self):
        self._running = False
