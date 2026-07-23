from typing import Any, Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.audit.repository import AuditRepository
from packages.config_manager.repository import ConfigurationRepository
from packages.config_manager.schemas import ConfigStatus, ConfigurationSet


class ConfigurationService:
    """Service orchestrating dynamic config changes with atomic transactions and mandatory audit logs."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ConfigurationRepository(session)
        self.audit_repo = AuditRepository(session)

    async def create_new_version(
        self,
        namespace: str,
        name: str,
        values: Dict[str, Any],
        actor_id: str = "system"
    ) -> ConfigurationSet:
        """Creates a new configuration DRAFT version."""
        next_ver = await self.repo.get_next_version_number(namespace, name)
        config_set = ConfigurationSet(
            namespace=namespace,
            name=name,
            version=next_ver,
            status=ConfigStatus.DRAFT,
            values=values,
            created_by=actor_id
        )
        created = await self.repo.create_version(config_set)
        
        # Write audit event
        await self.audit_repo.create_audit_event(
            audit_type="configuration",
            action="created",
            entity_type="configuration_set",
            entity_id=str(created.id),
            actor_id=actor_id,
            new_value=created.model_dump(mode="json"),
            reason=f"Created version {next_ver} for {namespace}/{name}"
        )
        return created

    async def activate_configuration(self, config_id: UUID, actor_id: str = "system") -> ConfigurationSet:
        """Activates configuration version and deactivates former active version, logging audit trail."""
        old_active = None
        target = await self.repo.get_by_id(config_id)
        if not target:
            raise ValueError(f"Configuration ID '{config_id}' not found")

        old_active = await self.repo.get_active_version(target.namespace, target.name)

        activated = await self.repo.activate_version(config_id)

        # Audit log activation
        await self.audit_repo.create_audit_event(
            audit_type="configuration",
            action="activated",
            entity_type="configuration_set",
            entity_id=str(config_id),
            actor_id=actor_id,
            previous_value=old_active.model_dump(mode="json") if old_active else None,
            new_value=activated.model_dump(mode="json"),
            reason=f"Activated version {activated.version} for {activated.namespace}/{activated.name}"
        )
        return activated
