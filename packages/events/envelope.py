from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventMetadata(BaseModel):
    """Metadata context attached to every domain event."""
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    source_service: str = "trading-service"
    environment: str = "development"
    actor_type: str = "system"
    actor_id: Optional[str] = None
    model_version: Optional[str] = None
    strategy_version: Optional[str] = None
    risk_policy_version: Optional[str] = None


class DomainEventEnvelope(BaseModel):
    """Universal Domain Event Envelope adhering to CloudEvents standard."""
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: Optional[UUID] = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None
    producer: str = "trading-system"
    schema_version: int = 1
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: EventMetadata = Field(default_factory=EventMetadata)
