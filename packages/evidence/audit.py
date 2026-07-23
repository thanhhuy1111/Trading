"""Phase 5: evidence lifecycle audit log.

In-memory by default so default tests stay offline (Section 4 rule 18) — a production
deployment can drain `EvidenceAuditLog.events` into `packages.audit.repository.AuditRepository`
(the existing DB-backed, append-only audit store) without changing this module's interface.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

EVIDENCE_CREATED = "evidence_created"
EVIDENCE_UPDATED = "evidence_updated"
EVIDENCE_DEGRADED = "evidence_degraded"
EVIDENCE_STALED = "evidence_staled"
EVIDENCE_DISABLED = "evidence_disabled"
LOOKUP_REJECTED = "lookup_rejected"


@dataclass(frozen=True)
class EvidenceAuditEvent:
    event_id: UUID = field(default_factory=uuid4)
    event_type: str = ""
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    key_summary: str = ""
    details: Optional[Dict[str, str]] = None


class EvidenceAuditLog:
    def __init__(self) -> None:
        self.events: List[EvidenceAuditEvent] = []

    def record(self, event_type: str, key_summary: str, details: Optional[Dict[str, str]] = None) -> EvidenceAuditEvent:
        event = EvidenceAuditEvent(event_type=event_type, key_summary=key_summary, details=details)
        self.events.append(event)
        return event

    def events_by_type(self, event_type: str) -> List[EvidenceAuditEvent]:
        return [e for e in self.events if e.event_type == event_type]


evidence_audit_log = EvidenceAuditLog()
