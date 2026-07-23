import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.events.envelope import DomainEventEnvelope


class OutboxRepository:
    """PostgreSQL Outbox Repository for atomic transaction writing and batch processing."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_event(self, event: DomainEventEnvelope, topic: str) -> UUID:
        """Saves a domain event into the event_outbox table within the active database transaction."""
        outbox_id = uuid4()
        query = text("""
            INSERT INTO event_outbox (
                id, event_id, topic, event_type, schema_version,
                aggregate_type, aggregate_id, payload, metadata, status, created_at
            ) VALUES (
                :id, :event_id, :topic, :event_type, :schema_version,
                :aggregate_type, :aggregate_id, :payload, :metadata, 'PENDING', :created_at
            )
        """)
        await self.session.execute(
            query,
            {
                "id": outbox_id,
                "event_id": event.event_id,
                "topic": topic,
                "event_type": event.event_type,
                "schema_version": event.schema_version,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "payload": json.dumps(event.payload),
                "metadata": json.dumps(event.metadata.model_dump()),
                "created_at": event.occurred_at
            }
        )
        return outbox_id

    async def fetch_and_lock_pending(self, worker_id: str, batch_size: int = 50) -> List[Dict[str, Any]]:
        """Atomically locks and fetches pending outbox events for publishing."""
        query = text("""
            WITH locked_rows AS (
                SELECT id FROM event_outbox
                WHERE status IN ('PENDING', 'FAILED')
                  AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                  AND (locked_at IS NULL OR locked_at < NOW() - INTERVAL '1 minute')
                ORDER BY created_at ASC
                LIMIT :batch_size
                FOR UPDATE SKIP LOCKED
            )
            UPDATE event_outbox
            SET status = 'PROCESSING',
                locked_at = NOW(),
                locked_by = :worker_id
            FROM locked_rows
            WHERE event_outbox.id = locked_rows.id
            RETURNING event_outbox.id, event_outbox.event_id, event_outbox.topic,
                      event_outbox.event_type, event_outbox.schema_version,
                      event_outbox.aggregate_type, event_outbox.aggregate_id,
                      event_outbox.payload, event_outbox.metadata, event_outbox.retry_count
        """)
        result = await self.session.execute(query, {"batch_size": batch_size, "worker_id": worker_id})
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def mark_published(self, outbox_id: UUID) -> None:
        """Marks outbox event as PUBLISHED."""
        query = text("""
            UPDATE event_outbox
            SET status = 'PUBLISHED',
                published_at = NOW(),
                locked_at = NULL,
                locked_by = NULL
            WHERE id = :id
        """)
        await self.session.execute(query, {"id": outbox_id})

    async def mark_failed(self, outbox_id: UUID, error: str, max_retries: int = 5) -> None:
        """Increments retry count, calculates exponential backoff, or moves to DEAD_LETTERED."""
        fetch_query = text("SELECT retry_count FROM event_outbox WHERE id = :id")
        result = await self.session.execute(fetch_query, {"id": outbox_id})
        retry_count = result.scalar() or 0
        retry_count += 1

        if retry_count >= max_retries:
            status = "DEAD_LETTERED"
            next_retry = None
        else:
            status = "FAILED"
            delay_seconds = 2 ** retry_count
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

        update_query = text("""
            UPDATE event_outbox
            SET status = :status,
                retry_count = :retry_count,
                next_retry_at = :next_retry,
                last_error = :error,
                locked_at = NULL,
                locked_by = NULL
            WHERE id = :id
        """)
        await self.session.execute(
            update_query,
            {
                "id": outbox_id,
                "status": status,
                "retry_count": retry_count,
                "next_retry": next_retry,
                "error": error
            }
        )
