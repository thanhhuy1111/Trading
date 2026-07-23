from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/data-quality", tags=["Data Guardian & Quality"])

data_issues_mock: List[Dict[str, Any]] = [
    {
        "id": str(uuid4()),
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "data_type": "order_book",
        "issue_code": "STALE_STREAM",
        "message": "Order book stream latency exceeded 10.0s threshold",
        "severity": "LOW",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "is_resolved": False
    }
]


@router.get("/status")
async def get_data_quality_status() -> Dict[str, Any]:
    return {
        "BTC/USDT": {
            "trades": "HEALTHY",
            "candles": "HEALTHY",
            "order_book": "HEALTHY",
            "overall": "HEALTHY"
        },
        "ETH/USDT": {
            "trades": "HEALTHY",
            "candles": "HEALTHY",
            "order_book": "HEALTHY",
            "overall": "HEALTHY"
        },
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("/issues")
async def list_quality_issues(severity: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    res = data_issues_mock
    if severity:
        res = [i for i in res if i.get("severity") == severity]
    return res


@router.get("/issues/{issue_id}")
async def get_quality_issue_by_id(issue_id: UUID) -> Dict[str, Any]:
    for issue in data_issues_mock:
        if issue.get("id") == str(issue_id):
            return issue
    raise HTTPException(status_code=404, detail="Quality issue not found")


@router.post("/issues/{issue_id}/acknowledge")
async def acknowledge_quality_issue(issue_id: UUID) -> Dict[str, Any]:
    for issue in data_issues_mock:
        if issue.get("id") == str(issue_id):
            issue["is_resolved"] = True
            return {"message": "Issue acknowledged and marked resolved", "issue": issue}
    raise HTTPException(status_code=404, detail="Quality issue not found")


@router.post("/resync/{symbol:path}")
async def resync_market_data_symbol(symbol: str) -> Dict[str, Any]:
    """Resyncs market data state for symbol ONLY. NO TRADING IMPACT."""
    return {
        "message": f"Triggered market data state resync for symbol '{symbol}'",
        "symbol": symbol,
        "action": "RESYNC",
        "triggered_at": datetime.now(timezone.utc).isoformat()
    }
