from typing import Any, Dict, List

from fastapi import APIRouter

from packages.common.config import settings
from packages.schemas.risk import RiskLimits

router = APIRouter(prefix="/risk", tags=["Risk Governor"])

risk_limits_state = RiskLimits(
    max_risk_per_trade_pct=settings.MAX_RISK_PER_TRADE_PCT,
    max_open_risk_pct=settings.MAX_OPEN_RISK_PCT,
    max_daily_loss_pct=settings.MAX_DAILY_LOSS_PCT,
    hard_stop_drawdown_pct=settings.HARD_STOP_DRAWDOWN_PCT,
)


@router.get("/status")
async def get_risk_status() -> Dict[str, Any]:
    return {
        "status": "NORMAL",
        "current_daily_loss_pct": 0.0,
        "current_drawdown_pct": 0.0,
        "current_open_risk_pct": 0.0,
        "kill_switch_active": False,
        "soft_stop_active": False,
        "risk_limits": risk_limits_state
    }


@router.get("/limits")
async def get_risk_limits() -> RiskLimits:
    return risk_limits_state


@router.put("/limits")
async def update_risk_limits(limits: RiskLimits) -> Dict[str, Any]:
    global risk_limits_state
    risk_limits_state = limits
    return {
        "message": "Risk limits updated successfully",
        "limits": risk_limits_state
    }


@router.get("/breaches")
async def get_risk_breaches() -> List[Dict[str, Any]]:
    return []
