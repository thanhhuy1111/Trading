from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class InboxRepository:
    """Manages consumer event idempotency checking via unique constraint (event_id, consumer_name)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_already_processed(self, event_id: UUID, consumer_name: str) -> bool:
        """Returns True if the event was already successfully processed by this consumer."""
        query = text("""
            SELECT status FROM event_inbox
            WHERE event_id = :event_id AND consumer_name = :consumer_name
        """)
        result = await self.session.execute(
            query,
            {"event_id": event_id, "consumer_name": consumer_name}
        )
        status = result.scalar()
        return status == "PROCESSED"

    async def start_processing(self, event_id: UUID, consumer_name: str, event_type: str) -> bool:
        """Attempts to register intent to process an event. Returns True if claimed, False if already registered."""
        inbox_id = uuid4()
        query = text("""
            INSERT INTO event_inbox (id, event_id, consumer_name, event_type, status, received_at)
            VALUES (:id, :event_id, :consumer_name, :event_type, 'PROCESSING', NOW())
            ON CONFLICT (event_id, consumer_name) DO NOTHING
        """)
        result = await self.session.execute(
            query,
            {
                "id": inbox_id,
                "event_id": event_id,
                "consumer_name": consumer_name,
                "event_type": event_type
            }
        )
        # Returns True if row was inserted (rowcount > 0)
        return result.rowcount > 0

    async def mark_processed(self, event_id: UUID, consumer_name: str) -> None:
        """Marks event as successfully PROCESSED by consumer."""
        query = text("""
            UPDATE event_inbox
            SET status = 'PROCESSED',
                processed_at = NOW()
            WHERE event_id = :event_id AND consumer_name = :consumer_name
        """)
        await self.session.execute(
            query,
            {"event_id": event_id, "consumer_name": consumer_name}
        )

    async def mark_failed(self, event_id: UUID, consumer_name: str, error: str) -> None:
        """Marks event as FAILED for retry or dead-letter decision."""
        query = text("""
            UPDATE event_inbox
            SET status = 'FAILED',
                retry_count = retry_count + 1,
                last_error = :error
            WHERE event_id = :event_id AND consumer_name = :consumer_name
        """)
        await self.session.execute(
            query,
            {"event_id": event_id, "consumer_name": consumer_name, "error": error}
        )
