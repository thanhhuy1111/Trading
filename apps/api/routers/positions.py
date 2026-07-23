from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter

from packages.positions.ledger import portfolio_ledger
from packages.positions.manager import position_manager

router = APIRouter(tags=["Position Manager & Portfolio Ledger"])


@router.get("/portfolio/accounts")
async def get_trading_account() -> Dict[str, Any]:
    return {
        "account_id": position_manager.account_id,
        "base_currency": "USDT",
        "status": "ACTIVE",
        "accounting_method": "WEIGHTED_AVERAGE"
    }


@router.get("/portfolio/balances")
async def get_portfolio_balances() -> Dict[str, Any]:
    return {
        "cash_balance": str(portfolio_ledger.cash_balance),
        "available_cash": str(portfolio_ledger.available_cash),
        "asset_balances": {k: str(v) for k, v in portfolio_ledger.asset_balances.items()}
    }


@router.get("/positions")
async def list_open_positions() -> List[Dict[str, Any]]:
    positions = list(position_manager.positions.values())
    return [p.model_dump(mode="json") for p in positions]


@router.get("/fills")
async def list_fill_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Real fill history for this account (most recent first)."""
    recent = position_manager.fill_history[-limit:]
    return [
        {
            "id": str(fill.fill_id),
            "symbol": fill.symbol,
            "side": fill.side,
            "quantity": str(fill.quantity),
            "fill_price": str(fill.price),
            "fee": str(fill.fee),
            "realized_pnl": str(pnl_entry.realized_pnl) if pnl_entry else None,
            "filled_at": fill.executed_at.isoformat(),
        }
        for fill, pnl_entry in reversed(recent)
    ]


@router.get("/portfolio/snapshots/latest")
async def get_latest_portfolio_snapshot() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    snap = position_manager.get_portfolio_snapshot(now)
    return snap.model_dump(mode="json")
