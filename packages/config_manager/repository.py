import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.config_manager.schemas import ConfigStatus, ConfigurationSet


class ConfigurationRepository:
    """PostgreSQL Repository for versioned configuration sets."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_version(self, config_set: ConfigurationSet) -> ConfigurationSet:
        """Creates a new DRAFT configuration version."""
        query = text("""
            INSERT INTO configuration_sets (
                id, namespace, name, version, status, values, checksum, created_by, created_at
            ) VALUES (
                :id, :namespace, :name, :version, :status, :values, :checksum, :created_by, NOW()
            )
        """)
        await self.session.execute(
            query,
            {
                "id": config_set.id,
                "namespace": config_set.namespace,
                "name": config_set.name,
                "version": config_set.version,
                "status": config_set.status.value,
                "values": json.dumps(config_set.values),
                "checksum": config_set.checksum,
                "created_by": config_set.created_by
            }
        )
        return config_set

    async def get_next_version_number(self, namespace: str, name: str) -> int:
        """Gets highest version number + 1 for namespace/name."""
        query = text(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM configuration_sets WHERE namespace = :ns AND name = :name"
        )
        res = await self.session.execute(query, {"ns": namespace, "name": name})
        return res.scalar() or 1

    async def get_active_version(self, namespace: str, name: str) -> Optional[ConfigurationSet]:
        """Gets currently ACTIVE configuration for namespace/name."""
        query = text("""
            SELECT id, namespace, name, version, status, values, checksum, created_by, created_at, activated_at
            FROM configuration_sets
            WHERE namespace = :ns AND name = :name AND status = 'ACTIVE'
            LIMIT 1
        """)
        res = await self.session.execute(query, {"ns": namespace, "name": name})
        row = res.mappings().first()
        if not row:
            return None
        return ConfigurationSet(
            id=row["id"],
            namespace=row["namespace"],
            name=row["name"],
            version=row["version"],
            status=ConfigStatus(row["status"]),
            values=json.loads(row["values"]) if isinstance(row["values"], str) else row["values"],
            checksum=row["checksum"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            activated_at=row["activated_at"]
        )

    async def activate_version(self, config_id: UUID) -> ConfigurationSet:
        """Atomically deactivates any existing ACTIVE version and activates target version."""
        # 1. Fetch target config
        fetch = text(
            "SELECT id, namespace, name, version, status, values, checksum, created_by "
            "FROM configuration_sets WHERE id = :id"
        )
        res = await self.session.execute(fetch, {"id": config_id})
        row = res.mappings().first()
        if not row:
            raise ValueError(f"Configuration set ID '{config_id}' not found")

        ns = row["namespace"]
        name = row["name"]

        # 2. Deactivate currently active version for namespace/name
        deactivate = text("""
            UPDATE configuration_sets
            SET status = 'INACTIVE', deactivated_at = NOW()
            WHERE namespace = :ns AND name = :name AND status = 'ACTIVE'
        """)
        await self.session.execute(deactivate, {"ns": ns, "name": name})

        # 3. Activate target version
        activate = text("""
            UPDATE configuration_sets
            SET status = 'ACTIVE', activated_at = NOW()
            WHERE id = :id
        """)
        await self.session.execute(activate, {"id": config_id})

        return await self.get_by_id(config_id)

    async def get_by_id(self, config_id: UUID) -> Optional[ConfigurationSet]:
        query = text("""
            SELECT id, namespace, name, version, status, values, checksum, created_by, created_at, activated_at,
                   deactivated_at
            FROM configuration_sets WHERE id = :id
        """)
        res = await self.session.execute(query, {"id": config_id})
        row = res.mappings().first()
        if not row:
            return None
        return ConfigurationSet(
            id=row["id"],
            namespace=row["namespace"],
            name=row["name"],
            version=row["version"],
            status=ConfigStatus(row["status"]),
            values=json.loads(row["values"]) if isinstance(row["values"], str) else row["values"],
            checksum=row["checksum"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            activated_at=row["activated_at"],
            deactivated_at=row["deactivated_at"]
        )

    async def list_configurations(
        self,
        namespace: Optional[str] = None,
        name: Optional[str] = None
    ) -> List[ConfigurationSet]:
        query_str = (
            "SELECT id, namespace, name, version, status, values, checksum, created_by, created_at, "
            "activated_at, deactivated_at FROM configuration_sets WHERE 1=1"
        )
        params: Dict[str, Any] = {}
        if namespace:
            query_str += " AND namespace = :ns"
            params["ns"] = namespace
        if name:
            query_str += " AND name = :name"
            params["name"] = name
        query_str += " ORDER BY namespace, name, version DESC"

        res = await self.session.execute(text(query_str), params)
        rows = res.mappings().all()
        configs = []
        for row in rows:
            configs.append(ConfigurationSet(
                id=row["id"],
                namespace=row["namespace"],
                name=row["name"],
                version=row["version"],
                status=ConfigStatus(row["status"]),
                values=json.loads(row["values"]) if isinstance(row["values"], str) else row["values"],
                checksum=row["checksum"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                activated_at=row["activated_at"],
                deactivated_at=row["deactivated_at"]
            ))
        return configs
