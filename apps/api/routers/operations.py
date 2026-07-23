from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from packages.telemetry.health import health_service
from packages.telemetry.incidents import incident_service
from packages.telemetry.lineage import lineage_service
from packages.telemetry.metrics import metrics_registry
from packages.telemetry.models import (
    IncidentStatus,
    OperationalIncident,
    PipelineLineageRecord,
)
from packages.telemetry.slo import slo_service

router = APIRouter(prefix="/operations", tags=["operations"])


class TransitionIncidentRequest(BaseModel):
    actor: str = "operator"
    reason: str = "Operations management action"
    note_text: Optional[str] = None


@router.get("/overview")
def get_operations_overview() -> Dict[str, Any]:
    overall_health = health_service.get_system_overall_status()
    open_incidents = [
        i for i in incident_service.incidents.values()
        if i.status in [IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING]
    ]

    return {
        "system_status": overall_health.value,
        "live_trading_enabled": False,
        "private_exchange_api_enabled": False,
        "open_incidents_count": len(open_incidents),
        "data_guardian_healthy": True,
        "pipeline_healthy": True,
        "risk_governor_status": "READY",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/health")
def get_health() -> Dict[str, Any]:
    return {
        "overall": health_service.get_system_overall_status().value,
        "components": {name: snap.model_dump(mode="json") for name, snap in health_service.component_health.items()}
    }


@router.get("/freshness")
def get_data_freshness() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "market_trade_age_seconds": 0.5,
        "candle_age_seconds": 12.0,
        "feature_snapshot_age_seconds": 12.1,
        "risk_snapshot_age_seconds": 2.0,
        "checked_at": now.isoformat()
    }


@router.get("/dependencies")
def get_dependencies_health() -> Dict[str, Any]:
    return {
        "postgresql": "HEALTHY",
        "redis": "HEALTHY",
        "binance_public_stream": "HEALTHY",
        "data_guardian": "HEALTHY",
        "prometheus_exporter": "HEALTHY"
    }


@router.get("/metrics/{domain}")
def get_domain_metrics(domain: str) -> Dict[str, Any]:
    return {
        "domain": domain,
        "status": "HEALTHY",
        "total_counter_keys": len(metrics_registry.counters),
        "total_gauge_keys": len(metrics_registry.gauges)
    }


@router.get("/pipeline/{correlation_id}", response_model=List[PipelineLineageRecord])
def get_pipeline_lineage(correlation_id: UUID) -> List[PipelineLineageRecord]:
    return lineage_service.get_lineage_by_correlation(correlation_id)


@router.get("/lineage", response_model=List[PipelineLineageRecord])
def get_all_lineage() -> List[PipelineLineageRecord]:
    return lineage_service.get_all_lineage(limit=100)


@router.get("/incidents", response_model=List[OperationalIncident])
def list_incidents() -> List[OperationalIncident]:
    return list(incident_service.incidents.values())


@router.get("/incidents/{incident_id}", response_model=OperationalIncident)
def get_incident(incident_id: UUID) -> OperationalIncident:
    inc = incident_service.incidents.get(incident_id)
    if not inc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return inc


@router.post("/incidents/{incident_id}/acknowledge", response_model=OperationalIncident)
def acknowledge_incident(incident_id: UUID, req: TransitionIncidentRequest) -> OperationalIncident:
    try:
        return incident_service.transition_incident(
            incident_id, IncidentStatus.ACKNOWLEDGED, actor=req.actor, reason=req.reason, note_text=req.note_text
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/incidents/{incident_id}/investigate", response_model=OperationalIncident)
def investigate_incident(incident_id: UUID, req: TransitionIncidentRequest) -> OperationalIncident:
    try:
        return incident_service.transition_incident(
            incident_id, IncidentStatus.INVESTIGATING, actor=req.actor, reason=req.reason, note_text=req.note_text
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/incidents/{incident_id}/resolve", response_model=OperationalIncident)
def resolve_incident(incident_id: UUID, req: TransitionIncidentRequest) -> OperationalIncident:
    try:
        return incident_service.transition_incident(
            incident_id, IncidentStatus.RESOLVED, actor=req.actor, reason=req.reason, note_text=req.note_text
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/incidents/{incident_id}/close", response_model=OperationalIncident)
def close_incident(incident_id: UUID, req: TransitionIncidentRequest) -> OperationalIncident:
    try:
        return incident_service.transition_incident(
            incident_id, IncidentStatus.CLOSED, actor=req.actor, reason=req.reason, note_text=req.note_text
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/slos")
def list_slos() -> List[Dict[str, Any]]:
    res = []
    for slo_id, slo in slo_service.definitions.items():
        latest = (
            slo_service.measurements[slo_id][-1].model_dump(mode="json")
            if slo_service.measurements[slo_id]
            else None
        )
        res.append({
            "definition": slo.model_dump(mode="json"),
            "latest_measurement": latest
        })
    return res


@router.get("/audit")
def list_audit_trail() -> List[Dict[str, Any]]:
    return [
        {
            "audit_id": "AUDIT_001",
            "action": "PAPER_SESSION_CREATED",
            "actor": "operator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": "Created paper session PAPER_ACCT_01"
        }
    ]
