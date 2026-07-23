from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Query

from packages.execution.engine import execution_engine
from packages.execution.simulator_adapter import simulator_exchange_adapter
from packages.risk.models import ApprovedOrder

router = APIRouter(tags=["Execution Engine & Simulator"])


@router.get("/execution/orders")
async def list_simulated_orders() -> List[Dict[str, Any]]:
    orders = list(simulator_exchange_adapter.orders.values())
    return [o.model_dump(mode="json") for o in orders]


@router.get("/execution/reports")
async def list_execution_reports(symbol: str = Query("BTC/USDT")) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    order = ApprovedOrder(
        risk_decision_id=uuid4(),
        intent_id=uuid4(),
        exchange="binance",
        symbol=symbol,
        side="BUY",
        approved_quantity=Decimal("0.192"),
        maximum_notional=Decimal("12492.48"),
        approved_stop_price=Decimal("63700.00"),
        maximum_entry_price=Decimal("65065.00"),
        maximum_entry_slippage_bps=Decimal("10.0"),
        expires_at=now + timedelta(minutes=15),
        status="PENDING_EXECUTION"
    )

    report, fills, sim_order = await execution_engine.execute_approved_order(order, now)
    return [report.model_dump(mode="json")]
