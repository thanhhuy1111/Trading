from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

from fastapi import APIRouter

from packages.schemas.portfolio import PortfolioSnapshot, Position

router = APIRouter(prefix="", tags=["Portfolio"])


@router.get("/portfolio")
async def get_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        timestamp=datetime.now(timezone.utc),
        total_nav=Decimal("100000.00"),
        cash_balance=Decimal("100000.00"),
        unrealized_pnl=Decimal("0.00"),
        realized_pnl_today=Decimal("0.00"),
        current_drawdown_pct=0.0,
        open_positions_count=0,
        open_risk_pct=0.0,
        is_kill_switch_active=False,
        system_mode="PAPER_TRADING"
    )


@router.get("/positions")
async def get_positions() -> List[Position]:
    return []


@router.get("/orders")
async def get_orders() -> List[Dict[str, Any]]:
    return []


@router.get("/fills")
async def get_fills() -> List[Dict[str, Any]]:
    return []


@router.get("/pnl")
async def get_pnl_summary() -> Dict[str, Any]:
    return {
        "is_mock_data": True,
        "total_pnl": 0.0,
        "daily_pnl": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fees_paid": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0
    }
