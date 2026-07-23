from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/audit-events", tags=["Audit Log"])

audit_events_mock: List[Dict[str, Any]] = []


@router.get("")
async def query_audit_events(
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = 50
) -> List[Dict[str, Any]]:
    results = audit_events_mock
    if entity_type:
        results = [e for e in results if e.get("entity_type") == entity_type]
    if action:
        results = [e for e in results if e.get("action") == action]
    return results[:limit]


@router.get("/{audit_id}")
async def get_audit_event_by_id(audit_id: UUID) -> Dict[str, Any]:
    for ev in audit_events_mock:
        if ev.get("audit_id") == str(audit_id):
            return ev
    raise HTTPException(status_code=404, detail="Audit log entry not found")
