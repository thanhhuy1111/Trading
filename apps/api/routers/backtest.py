from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/backtests", tags=["Backtest Engine"])


class BacktestRequest(BaseModel):
    symbols: List[str] = ["BTCUSDT"]
    start_date: str = "2024-01-01"
    end_date: str = "2024-06-01"
    initial_capital: float = 100000.0
    timeframes: List[str] = ["15m", "1h"]


@router.post("")
async def create_backtest(request: BacktestRequest) -> Dict[str, Any]:
    run_id = str(uuid4())
    return {
        "run_id": run_id,
        "status": "QUEUED",
        "request": request,
        "created_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("")
async def list_backtests() -> List[Dict[str, Any]]:
    return []


@router.get("/{run_id}")
async def get_backtest_run(run_id: str) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "COMPLETED",
        "total_return_pct": 14.5,
        "sharpe_ratio": 1.92,
        "max_drawdown_pct": -4.2,
        "win_rate": 0.59,
        "total_trades": 88
    }


@router.get("/{run_id}/trades")
async def get_backtest_trades(run_id: str) -> List[Dict[str, Any]]:
    return []
