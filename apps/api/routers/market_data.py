from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from packages.market_data.models import Timeframe
from packages.market_data.symbol_registry import symbol_registry

router = APIRouter(prefix="/market-data", tags=["Market Data Platform"])

ingestion_jobs_mock: List[Dict[str, Any]] = []


class IngestionJobRequest(BaseModel):
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: Timeframe = Timeframe.M1
    start_time: datetime
    end_time: datetime


@router.get("/exchanges")
async def list_exchanges() -> List[Dict[str, Any]]:
    return [
        {
            "exchange_id": "binance",
            "name": "Binance Public Spot Exchange",
            "is_active": True,
            "rate_limit_ratio": 0.8,
            "supported_timeframes": ["1m", "5m", "15m", "1h", "4h"]
        }
    ]


@router.get("/symbols")
async def list_symbols() -> List[Dict[str, Any]]:
    symbols = symbol_registry.list_canonical_symbols()
    res = []
    for sym in symbols:
        info = symbol_registry.get_symbol_info(sym)
        if info:
            res.append(info.model_dump(mode="json"))
    return res


@router.get("/candles")
async def get_candles(
    symbol: str = Query("BTC/USDT"),
    timeframe: Timeframe = Timeframe.M1,
    limit: int = 100
) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    base_price = Decimal("65000.00") if "BTC" in symbol else Decimal("3500.00")
    candles = []
    for i in range(limit):
        candles.append({
            "exchange": "binance",
            "symbol": symbol,
            "timeframe": timeframe.value,
            "open_time": now.isoformat(),
            "close_time": now.isoformat(),
            "open_price": str(base_price + Decimal(i)),
            "high_price": str(base_price + Decimal(i) + Decimal("10.0")),
            "low_price": str(base_price + Decimal(i) - Decimal("5.0")),
            "close_price": str(base_price + Decimal(i) + Decimal("2.0")),
            "volume": "15.4",
            "is_closed": True
        })
    return candles


@router.get("/trades")
async def get_recent_trades(symbol: str = Query("BTC/USDT"), limit: int = 50) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    base_price = "65000.00" if "BTC" in symbol else "3500.00"
    return [
        {
            "exchange": "binance",
            "symbol": symbol,
            "trade_id": f"tr_{i}",
            "price": base_price,
            "quantity": "0.25",
            "side": "BUY" if i % 2 == 0 else "SELL",
            "exchange_timestamp": now,
            "data_quality_status": "HEALTHY"
        }
        for i in range(limit)
    ]


@router.get("/order-book/{symbol:path}")
async def get_order_book_snapshot(symbol: str, depth: int = 20) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    base_price = Decimal("65000.00") if "BTC" in symbol else Decimal("3500.00")
    bids = [{"price": str(base_price - Decimal(i + 1)), "quantity": "1.5"} for i in range(depth)]
    asks = [{"price": str(base_price + Decimal(i + 1)), "quantity": "1.8"} for i in range(depth)]
    return {
        "exchange": "binance",
        "symbol": symbol,
        "sequence_id": 105432,
        "bids": bids,
        "asks": asks,
        "exchange_timestamp": now,
        "data_quality_status": "HEALTHY"
    }


@router.get("/connections")
async def get_websocket_connections() -> List[Dict[str, Any]]:
    return [
        {
            "connection_id": "ws_conn_binance_spot",
            "exchange": "binance",
            "state": "CONNECTED",
            "reconnect_count": 0,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None
        }
    ]


@router.get("/ingestion-jobs")
async def list_ingestion_jobs() -> List[Dict[str, Any]]:
    return ingestion_jobs_mock


@router.post("/ingestion-jobs")
async def create_ingestion_job(req: IngestionJobRequest) -> Dict[str, Any]:
    job = {
        "id": str(uuid4()),
        "exchange": req.exchange,
        "symbol": req.symbol,
        "timeframe": req.timeframe.value,
        "start_time": req.start_time.isoformat(),
        "end_time": req.end_time.isoformat(),
        "status": "RUNNING",
        "processed_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    ingestion_jobs_mock.append(job)
    return job


@router.post("/ingestion-jobs/{job_id}/stop")
async def stop_ingestion_job(job_id: UUID) -> Dict[str, Any]:
    for j in ingestion_jobs_mock:
        if j.get("id") == str(job_id):
            j["status"] = "STOPPED"
            return {"message": "Ingestion job stopped", "job": j}
    raise HTTPException(status_code=404, detail="Ingestion job not found")
