from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AuditEvent(BaseModel):
    """Immutable audit trail log event."""
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str  # e.g., INTENT_CREATED, RISK_APPROVED, ORDER_SUBMITTED, KILL_SWITCH_TRIGGERED
    service_name: str
    actor: str = "system"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Incident(BaseModel):
    """System operational incident."""
    incident_id: UUID = Field(default_factory=uuid4)
    severity: IncidentSeverity
    service_name: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
