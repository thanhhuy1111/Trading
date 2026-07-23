from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/events", tags=["Events & Outbox"])

outbox_events_mock: List[Dict[str, Any]] = []


@router.get("/outbox")
async def get_outbox_events(
    status: str = Query(
        "PENDING",
        description="Filter outbox by status: PENDING, PROCESSING, PUBLISHED, FAILED, DEAD_LETTERED"
    ),
    limit: int = 50
) -> List[Dict[str, Any]]:
    return [e for e in outbox_events_mock if e.get("status") == status][:limit]


@router.get("/outbox/{event_id}")
async def get_outbox_event_by_id(event_id: UUID) -> Dict[str, Any]:
    for ev in outbox_events_mock:
        if ev.get("event_id") == str(event_id):
            return ev
    raise HTTPException(status_code=404, detail="Outbox event not found")


@router.get("/dead-letter")
async def get_dead_letter_events(limit: int = 50) -> List[Dict[str, Any]]:
    return [e for e in outbox_events_mock if e.get("status") == "DEAD_LETTERED"][:limit]


@router.post("/{event_id}/retry")
async def retry_failed_event(event_id: UUID) -> Dict[str, Any]:
    for ev in outbox_events_mock:
        if ev.get("event_id") == str(event_id):
            if ev.get("status") not in ["FAILED", "DEAD_LETTERED"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Only FAILED or DEAD_LETTERED events can be retried. Current status: {ev.get('status')}"
                )
            ev["status"] = "PENDING"
            ev["retry_count"] = ev.get("retry_count", 0) + 1
            return {"message": "Event queued for retry", "event": ev}
    raise HTTPException(status_code=404, detail="Event not found")
