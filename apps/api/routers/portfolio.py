from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

from fastapi import APIRouter

from packages.common.config import settings
from packages.positions.manager import position_manager
from packages.risk.models import RiskState
from packages.risk.state_machine import risk_state_machine
from packages.schemas.portfolio import PortfolioSnapshot

router = APIRouter(prefix="", tags=["Portfolio"])


@router.get("/portfolio")
async def get_portfolio() -> PortfolioSnapshot:
    now = datetime.now(timezone.utc)
    snap = position_manager.get_portfolio_snapshot(now)
    nav = snap.nav
    open_risk_pct = float(snap.open_risk_amount / nav) if nav > Decimal("0") else 0.0
    return PortfolioSnapshot(
        timestamp=now,
        total_nav=nav,
        cash_balance=snap.cash_balance,
        unrealized_pnl=snap.unrealized_pnl,
        realized_pnl_today=snap.realized_pnl_today,
        current_drawdown_pct=float(snap.drawdown_pct),
        open_positions_count=len(snap.positions),
        open_risk_pct=open_risk_pct,
        is_kill_switch_active=risk_state_machine.state == RiskState.HARD_STOP,
        system_mode=settings.SYSTEM_MODE
    )


# NOTE: GET /positions is served by apps/api/routers/positions.py (reads the real
# position_manager). A duplicate mock route used to be defined here and, because this router
# is registered before positions.router in main.py, silently shadowed the real one — every
# caller of GET /positions always got [] regardless of actual open positions. Removed.


@router.get("/orders")
async def get_orders() -> List[Dict[str, Any]]:
    # Honestly empty: this system's execution model has no resting/GTC order book — every
    # submitted order is a marketable-limit/IOC that fills or is rejected immediately (see
    # packages/execution/simulator_adapter.py, packages/paper/adapter.py). There is nothing
    # that stays "pending". Executed history is GET /fills (real, see positions.py).
    return []


# NOTE: GET /fills is served by apps/api/routers/positions.py (reads the real
# position_manager.fill_history). A duplicate mock route used to be defined here and, because
# this router is registered before positions.router in main.py, would have silently shadowed
# the real one exactly like the /positions bug above — removed rather than left as a stub.


@router.get("/pnl")
async def get_pnl_summary() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    snap = position_manager.get_portfolio_snapshot(now)
    daily_pnl = float(position_manager.realized_pnl_window("DAILY", now))
    fills = position_manager.fill_history
    total_fees = sum((f.fee for f, _ in fills), Decimal("0"))
    total_realized = sum((p.realized_pnl for _, p in fills if p), Decimal("0"))
    wins = [p.realized_pnl for _, p in fills if p and p.realized_pnl > Decimal("0")]
    losses = [p.realized_pnl for _, p in fills if p and p.realized_pnl < Decimal("0")]
    closed_trades = len(wins) + len(losses)
    win_rate = (len(wins) / closed_trades) if closed_trades > 0 else 0.0
    gross_win = sum(wins, Decimal("0"))
    gross_loss = abs(sum(losses, Decimal("0")))
    profit_factor = float(gross_win / gross_loss) if gross_loss > Decimal("0") else 0.0
    return {
        "total_pnl": float(total_realized + snap.unrealized_pnl),
        "daily_pnl": daily_pnl,
        "realized_pnl": float(total_realized),
        "unrealized_pnl": float(snap.unrealized_pnl),
        "fees_paid": float(total_fees),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
    }
