from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

from packages.common.logger import logger
from packages.telemetry.models import ComponentHealthSnapshot, ComponentHealthStatus


class HealthService:
    """Manages component health readiness, dependency status, and system operational state."""

    def __init__(self) -> None:
        self.component_health: Dict[str, ComponentHealthSnapshot] = {}

    def update_component_health(
        self,
        component_name: str,
        status: ComponentHealthStatus,
        latency_ms: float = 0.0,
        is_failure: bool = False
    ) -> ComponentHealthSnapshot:
        now = datetime.now(timezone.utc)
        existing = self.component_health.get(component_name)

        fail_cnt = (existing.failure_count + 1) if (existing and is_failure) else (1 if is_failure else 0)
        last_succ = now if not is_failure else (existing.last_successful_op if existing else None)
        last_fail = now if is_failure else (existing.last_failure if existing else None)

        snapshot = ComponentHealthSnapshot(
            health_id=uuid4(),
            component_name=component_name,
            status=status,
            last_successful_op=last_succ,
            last_failure=last_fail,
            failure_count=fail_cnt,
            latency_ms=latency_ms,
            checked_at=now
        )

        self.component_health[component_name] = snapshot
        logger.info("Component health updated", extra={"component": component_name, "status": status.value})
        return snapshot

    def get_system_overall_status(self) -> ComponentHealthStatus:
        if not self.component_health:
            return ComponentHealthStatus.HEALTHY

        statuses = [snap.status for snap in self.component_health.values()]
        if ComponentHealthStatus.HALTED in statuses:
            return ComponentHealthStatus.HALTED
        if ComponentHealthStatus.UNHEALTHY in statuses:
            return ComponentHealthStatus.UNHEALTHY
        if ComponentHealthStatus.DEGRADED in statuses:
            return ComponentHealthStatus.DEGRADED
        if ComponentHealthStatus.UNKNOWN in statuses:
            return ComponentHealthStatus.UNKNOWN
        return ComponentHealthStatus.HEALTHY


health_service = HealthService()
