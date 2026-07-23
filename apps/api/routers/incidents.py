from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/incidents", tags=["Incidents & Governance"])

incidents_db: List[Dict[str, Any]] = []


@router.get("")
async def get_incidents() -> List[Dict[str, Any]]:
    return incidents_db


@router.post("/{incident_id}/acknowledge")
async def acknowledge_incident(incident_id: str) -> Dict[str, Any]:
    for inc in incidents_db:
        if inc["incident_id"] == incident_id:
            inc["is_acknowledged"] = True
            inc["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
            return {"message": "Incident acknowledged", "incident": inc}
    raise HTTPException(status_code=404, detail="Incident not found")
