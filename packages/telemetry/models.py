from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ComponentHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


class TelemetryContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    span_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: Optional[UUID] = None

    event_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    backtest_session_id: Optional[UUID] = None
    paper_session_id: Optional[UUID] = None

    account_id: Optional[str] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None

    schema_version: int = 1


class PipelineLineageRecord(BaseModel):
    lineage_id: UUID = Field(default_factory=uuid4)
    entity_type: str
    entity_id: UUID
    parent_entity_type: Optional[str] = None
    parent_entity_id: Optional[UUID] = None
    correlation_id: UUID
    causation_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    symbol: Optional[str] = None
    service: str = "trading_pipeline"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OperationalIncident(BaseModel):
    incident_id: UUID = Field(default_factory=uuid4)
    fingerprint: str
    severity: IncidentSeverity = IncidentSeverity.WARNING
    status: IncidentStatus = IncidentStatus.OPEN
    component: str
    incident_type: str
    title: str
    description: str
    first_detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    occurrence_count: int = 1
    correlation_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    symbol: Optional[str] = None
    runbook_reference: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
    schema_version: int = 1


class ComponentHealthSnapshot(BaseModel):
    health_id: UUID = Field(default_factory=uuid4)
    component_name: str
    status: ComponentHealthStatus = ComponentHealthStatus.HEALTHY
    last_successful_op: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    failure_count: int = 0
    latency_ms: float = 0.0
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SloDefinition(BaseModel):
    slo_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str
    target_percentage: Decimal = Field(default=Decimal("99.90"), ge=Decimal("0.0"), le=Decimal("100.0"))
    window_days: int = 30
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SloMeasurement(BaseModel):
    measurement_id: UUID = Field(default_factory=uuid4)
    slo_id: UUID
    current_value_pct: Decimal
    error_budget_remaining_pct: Decimal
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AlertRule(BaseModel):
    rule_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str
    severity: IncidentSeverity = IncidentSeverity.WARNING
    component: str
    for_duration_seconds: int = 60
    runbook_url: Optional[str] = None
    is_enabled: bool = True


class AlertOccurrence(BaseModel):
    occurrence_id: UUID = Field(default_factory=uuid4)
    rule_id: UUID
    severity: IncidentSeverity
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
