from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from packages.execution.simulator_adapter import simulator_exchange_adapter

router = APIRouter(tags=["Execution Engine & Simulator"])


@router.get("/execution/orders")
async def list_simulated_orders() -> List[Dict[str, Any]]:
    orders = list(simulator_exchange_adapter.orders.values())
    return [o.model_dump(mode="json") for o in orders]


@router.get("/execution/reports")
async def list_execution_reports(symbol: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Real order+fill summaries derived from the simulator adapter's own state.

    NOTE: this used to fabricate a fake BUY order and actually EXECUTE it via
    execution_engine.execute_approved_order on every GET call — a read endpoint with a real
    side effect (it created a new simulated fill each time the dashboard polled it). Fixed to
    be genuinely read-only: it only reports on orders/fills that have actually happened.
    """
    reports = []
    for client_order_id, order in simulator_exchange_adapter.orders.items():
        if symbol and order.symbol != symbol:
            continue
        fills = simulator_exchange_adapter.fills.get(client_order_id, [])
        reports.append({
            "client_order_id": str(client_order_id),
            "symbol": order.symbol,
            "status": order.status.value if hasattr(order.status, "value") else order.status,
            "filled_quantity": str(order.filled_quantity),
            "average_fill_price": str(order.average_fill_price) if order.average_fill_price else None,
            "cumulative_fee": str(order.cumulative_fee),
            "fill_count": len(fills),
            "submitted_at": order.submitted_at.isoformat(),
        })
    return reports
