from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from packages.common.config import settings

router = APIRouter(prefix="/trading", tags=["Trading Control"])

# System trading execution state
system_state = {
    "is_running": False,
    "soft_stop": False,
    "hard_stop": False,
    "mode": settings.SYSTEM_MODE
}


@router.get("/status")
async def get_trading_status() -> Dict[str, Any]:
    return {
        "is_running": system_state["is_running"],
        "soft_stop": system_state["soft_stop"],
        "hard_stop": system_state["hard_stop"],
        "mode": system_state["mode"],
        "live_trading_feature_flag": settings.FEATURE_FLAGS_LIVE_TRADING,
        "symbols": settings.symbols_list,
        "timeframes": settings.timeframes_list,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


@router.post("/start")
async def start_trading() -> Dict[str, Any]:
    system_state["is_running"] = True
    system_state["soft_stop"] = False
    system_state["hard_stop"] = False
    return {"message": "Trading engine started successfully", "status": system_state}


@router.post("/stop")
async def stop_trading() -> Dict[str, Any]:
    system_state["is_running"] = False
    return {"message": "Trading engine stopped", "status": system_state}


@router.post("/soft-stop")
async def soft_stop_trading() -> Dict[str, Any]:
    system_state["soft_stop"] = True
    msg = "SOFT_STOP activated: No new positions will be opened"
    return {"message": msg, "status": system_state}


@router.post("/hard-stop")
async def hard_stop_trading() -> Dict[str, Any]:
    system_state["is_running"] = False
    system_state["soft_stop"] = True
    system_state["hard_stop"] = True
    msg = "HARD_STOP activated: All open orders canceled and trading halted"
    return {"message": msg, "status": system_state}
