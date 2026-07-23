from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.audit.repository import AuditRepository
from packages.common.logger import logger


class AuditLogger:
    """High-level audit logger wrapping AuditRepository."""

    def __init__(self, session: AsyncSession):
        self.repo = AuditRepository(session)

    async def log_action(
        self,
        audit_type: str,
        action: str,
        entity_type: str,
        entity_id: str,
        actor_id: str = "system",
        previous_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None
    ) -> UUID:
        logger.info(
            "Audit event logged",
            extra={
                "audit_type": audit_type,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor": actor_id
            }
        )
        return await self.repo.create_audit_event(
            audit_type=audit_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            previous_value=previous_value,
            new_value=new_value,
            reason=reason
        )
