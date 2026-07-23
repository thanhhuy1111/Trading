from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/configurations", tags=["Configuration Manager"])

config_sets_mock: List[Dict[str, Any]] = [
    {
        "id": str(uuid4()),
        "namespace": "risk",
        "name": "default_risk_policy",
        "version": 1,
        "status": "ACTIVE",
        "values": {
            "max_risk_per_trade_pct": "0.0025",
            "max_open_risk_pct": "0.015",
            "max_daily_loss_pct": "0.015",
            "hard_stop_drawdown_pct": "0.08"
        },
        "checksum": "a1b2c3d4e5f67890",
        "created_by": "system",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "activated_at": datetime.now(timezone.utc).isoformat()
    }
]


class CreateConfigRequest(BaseModel):
    namespace: str
    name: str
    values: Dict[str, Any]
    created_by: str = "operator"


@router.get("")
async def list_configurations(
    namespace: Optional[str] = Query(None),
    name: Optional[str] = Query(None)
) -> List[Dict[str, Any]]:
    res = config_sets_mock
    if namespace:
        res = [c for c in res if c.get("namespace") == namespace]
    if name:
        res = [c for c in res if c.get("name") == name]
    return res


@router.get("/{namespace}/{name}")
async def get_active_configuration(namespace: str, name: str) -> Dict[str, Any]:
    for c in config_sets_mock:
        if c.get("namespace") == namespace and c.get("name") == name and c.get("status") == "ACTIVE":
            return c
    raise HTTPException(status_code=404, detail=f"Active config for {namespace}/{name} not found")


@router.post("")
async def create_configuration_draft(req: CreateConfigRequest) -> Dict[str, Any]:
    # Calculate version
    existing = [c for c in config_sets_mock if c.get("namespace") == req.namespace and c.get("name") == req.name]
    max_ver = max([c.get("version", 0) for c in existing], default=0)
    new_ver = max_ver + 1

    new_config = {
        "id": str(uuid4()),
        "namespace": req.namespace,
        "name": req.name,
        "version": new_ver,
        "status": "DRAFT",
        "values": req.values,
        "checksum": "mock_checksum",
        "created_by": req.created_by,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    config_sets_mock.append(new_config)
    return new_config


@router.post("/{config_id}/activate")
async def activate_configuration(config_id: UUID) -> Dict[str, Any]:
    target = None
    for c in config_sets_mock:
        if c.get("id") == str(config_id):
            target = c
            break

    if not target:
        raise HTTPException(status_code=404, detail="Configuration set not found")

    # Deactivate current active for namespace/name
    for c in config_sets_mock:
        if (
            c.get("namespace") == target["namespace"]
            and c.get("name") == target["name"]
            and c.get("status") == "ACTIVE"
        ):
            c["status"] = "INACTIVE"
            c["deactivated_at"] = datetime.now(timezone.utc).isoformat()

    target["status"] = "ACTIVE"
    target["activated_at"] = datetime.now(timezone.utc).isoformat()
    return {"message": "Configuration activated successfully", "config": target}


@router.post("/{config_id}/deactivate")
async def deactivate_configuration(config_id: UUID) -> Dict[str, Any]:
    for c in config_sets_mock:
        if c.get("id") == str(config_id):
            c["status"] = "INACTIVE"
            c["deactivated_at"] = datetime.now(timezone.utc).isoformat()
            return {"message": "Configuration deactivated", "config": c}
    raise HTTPException(status_code=404, detail="Configuration set not found")


@router.get("/{namespace}/{name}/history")
async def get_configuration_history(namespace: str, name: str) -> List[Dict[str, Any]]:
    return [c for c in config_sets_mock if c.get("namespace") == namespace and c.get("name") == name]
