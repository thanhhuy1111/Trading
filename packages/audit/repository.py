import json
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.audit.redactor import SensitiveDataRedactor


class AuditRepository:
    """Append-Only Audit Repository. Strictly provides create and query operations ONLY."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_audit_event(
        self,
        audit_type: str,
        action: str,
        entity_type: str,
        entity_id: str,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        correlation_id: Optional[UUID] = None,
        event_id: Optional[UUID] = None,
        previous_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
        source_service: str = "trading-api",
        source_ip: Optional[str] = None
    ) -> UUID:
        """Appends an immutable audit event log record."""
        audit_id = uuid4()
        query = text("""
            INSERT INTO audit_events (
                event_id, event_type, service_name, actor, timestamp, payload
            ) VALUES (
                :event_id, :event_type, :service_name, :actor, NOW(), :payload
            )
        """)

        payload_dict = {
            "audit_id": str(audit_id),
            "audit_type": audit_type,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "correlation_id": str(correlation_id) if correlation_id else None,
            "previous_value": SensitiveDataRedactor.redact(previous_value or {}),
            "new_value": SensitiveDataRedactor.redact(new_value or {}),
            "reason": reason,
            "source_ip": source_ip
        }

        await self.session.execute(
            query,
            {
                "event_id": audit_id,
                "event_type": f"audit.{entity_type}.{action}",
                "service_name": source_service,
                "actor": actor_id or actor_type,
                "payload": json.dumps(payload_dict)
            }
        )
        return audit_id

    async def query_audit_events(
        self,
        entity_type: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Queries immutable audit log records."""
        query_str = "SELECT event_id, event_type, service_name, actor, timestamp, payload FROM audit_events WHERE 1=1"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}

        if entity_type:
            query_str += " AND event_type LIKE :entity_filter"
            params["entity_filter"] = f"audit.{entity_type}.%"

        query_str += " ORDER BY timestamp DESC LIMIT :limit OFFSET :offset"
        result = await self.session.execute(text(query_str), params)
        rows = result.mappings().all()

        events = []
        for r in rows:
            p = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            ts = r["timestamp"].isoformat() if hasattr(r["timestamp"], "isoformat") else str(r["timestamp"])
            events.append({
                "audit_id": str(r["event_id"]),
                "event_type": r["event_type"],
                "service_name": r["service_name"],
                "actor": r["actor"],
                "timestamp": ts,
                "payload": p
            })
        return events

    async def get_by_id(self, audit_id: UUID) -> Optional[Dict[str, Any]]:
        """Retrieves a single audit log record by ID."""
        query = text("""
            SELECT event_id, event_type, service_name, actor, timestamp, payload
            FROM audit_events WHERE event_id = :id
        """)
        result = await self.session.execute(query, {"id": audit_id})
        row = result.mappings().first()
        if not row:
            return None
        p = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        ts_val = row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"])
        return {
            "audit_id": str(row["event_id"]),
            "event_type": row["event_type"],
            "service_name": row["service_name"],
            "actor": row["actor"],
            "timestamp": ts_val,
            "payload": p
        }
