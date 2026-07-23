from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.telemetry.models import (
    IncidentSeverity,
    IncidentStatus,
    OperationalIncident,
)


class IncidentService:
    """Manages operational incidents, state transitions, fingerprint deduplication, and audit notes."""

    VALID_INCIDENT_TRANSITIONS: Dict[IncidentStatus, List[IncidentStatus]] = {
        IncidentStatus.OPEN: [IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED],
        IncidentStatus.ACKNOWLEDGED: [IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATED, IncidentStatus.RESOLVED],
        IncidentStatus.INVESTIGATING: [IncidentStatus.MITIGATED, IncidentStatus.RESOLVED],
        IncidentStatus.MITIGATED: [IncidentStatus.RESOLVED],
        IncidentStatus.RESOLVED: [IncidentStatus.CLOSED],
        IncidentStatus.CLOSED: [],
    }

    def __init__(self) -> None:
        self.incidents: Dict[UUID, OperationalIncident] = {}
        self.fingerprint_index: Dict[str, UUID] = {}
        self.notes: Dict[UUID, List[Dict[str, Any]]] = {}

    def report_incident(
        self,
        fingerprint: str,
        severity: IncidentSeverity,
        component: str,
        incident_type: str,
        title: str,
        description: str,
        correlation_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        symbol: Optional[str] = None,
        runbook_reference: Optional[str] = None
    ) -> OperationalIncident:
        now = datetime.now(timezone.utc)

        # Fingerprint deduplication check
        if fingerprint in self.fingerprint_index:
            inc_id = self.fingerprint_index[fingerprint]
            existing = self.incidents[inc_id]
            if existing.status not in [IncidentStatus.RESOLVED, IncidentStatus.CLOSED]:
                existing.occurrence_count += 1
                existing.last_detected_at = now
                logger.info(
                    "Incident occurrence deduplicated",
                    extra={"fingerprint": fingerprint, "count": existing.occurrence_count}
                )
                return existing

        incident_id = uuid4()
        inc = OperationalIncident(
            incident_id=incident_id,
            fingerprint=fingerprint,
            severity=severity,
            status=IncidentStatus.OPEN,
            component=component,
            incident_type=incident_type,
            title=title,
            description=description,
            first_detected_at=now,
            last_detected_at=now,
            occurrence_count=1,
            correlation_id=correlation_id,
            session_id=session_id,
            symbol=symbol,
            runbook_reference=runbook_reference
        )

        self.incidents[incident_id] = inc
        self.fingerprint_index[fingerprint] = incident_id
        self.notes[incident_id] = []

        logger.warning(
            "Operational incident opened",
            extra={"incident_id": str(incident_id), "title": title, "severity": severity.value}
        )
        return inc

    def transition_incident(
        self,
        incident_id: UUID,
        to_status: IncidentStatus,
        actor: str = "SYSTEM",
        reason: str = "Status update",
        note_text: Optional[str] = None
    ) -> OperationalIncident:
        inc = self.incidents.get(incident_id)
        if not inc:
            raise ValueError(f"INCIDENT_ERROR: Incident {incident_id} not found")

        current = inc.status
        allowed = self.VALID_INCIDENT_TRANSITIONS.get(current, [])

        if to_status not in allowed:
            raise ValueError(
                f"INVALID_INCIDENT_TRANSITION: Cannot transition incident from {current.value} to {to_status.value}"
            )

        inc.status = to_status
        now = datetime.now(timezone.utc)

        if to_status == IncidentStatus.ACKNOWLEDGED:
            inc.acknowledged_at = now
            inc.acknowledged_by = actor
        elif to_status == IncidentStatus.RESOLVED:
            inc.resolved_at = now
            inc.resolution_note = reason

        if note_text:
            self.notes[incident_id].append({
                "note_id": str(uuid4()),
                "author": actor,
                "note_text": note_text,
                "created_at": now.isoformat()
            })

        logger.info(
            "Incident status transitioned",
            extra={"incident_id": str(incident_id), "from": current.value, "to": to_status.value}
        )
        return inc


incident_service = IncidentService()
