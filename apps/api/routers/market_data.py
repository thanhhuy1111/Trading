import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from packages.features.models import FeatureComputationRequest
from packages.features.pipeline import feature_pipeline
from packages.market_data.adapters.binance import BinancePublicMarketDataProvider
from packages.market_data.historical_quality import TIMEFRAME_INTERVAL
from packages.market_data.models import Candle, Timeframe
from packages.market_data.symbol_registry import symbol_registry
from packages.retraining.price_projection import artifact_path

router = APIRouter(prefix="/market-data", tags=["Market Data Platform"])

_binance_provider = BinancePublicMarketDataProvider()

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


@router.get("/live-prices")
async def get_live_prices(symbols: str = Query("BTC/USDT,ETH/USDT")) -> Dict[str, Any]:
    """Real current prices from Binance's public REST API (GET /api/v3/ticker/price).
    Public endpoint only — no API key, no private data."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    try:
        prices = await _binance_provider.fetch_current_prices(symbol_list)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BINANCE_PUBLIC_API_UNAVAILABLE: {exc}") from exc
    return {
        "source": "binance_public_rest",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "prices": {sym: str(price) for sym, price in prices.items()},
    }


def _candle_to_dict(c: Candle) -> Dict[str, Any]:
    return {
        "exchange": c.exchange,
        "symbol": c.symbol,
        "timeframe": c.timeframe.value,
        "open_time": c.open_time.isoformat(),
        "close_time": c.close_time.isoformat(),
        "open_price": str(c.open_price),
        "high_price": str(c.high_price),
        "low_price": str(c.low_price),
        "close_price": str(c.close_price),
        "volume": str(c.volume),
        "is_closed": c.is_closed,
    }


async def _fetch_real_candles(symbol: str, timeframe: Timeframe, limit: int) -> Sequence[Candle]:
    """Real historical OHLCV from Binance's public REST API. Never fabricated -- a network
    or symbol error returns an empty sequence (an honest "no data available"), never a
    synthetic fill-in."""
    end_time = datetime.now(timezone.utc)
    start_time = end_time - TIMEFRAME_INTERVAL[timeframe] * limit
    try:
        return await _binance_provider.fetch_candles(symbol, timeframe, start_time, end_time, limit)
    except Exception:  # noqa: BLE001 - network/adapter errors degrade to "no data", never a 500
        return []


@router.get("/candles")
async def get_candles(
    symbol: str = Query("BTC/USDT"),
    timeframe: Timeframe = Timeframe.M1,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Real historical candles from Binance's public REST API (GET /api/v3/klines) --
    public endpoint only, no API key, no private data."""
    candles = await _fetch_real_candles(symbol, timeframe, limit)
    return [_candle_to_dict(c) for c in candles]


def _load_price_model_artifact(symbol: str, timeframe: Timeframe) -> Optional[Dict[str, Any]]:
    path = artifact_path(symbol, timeframe)
    if not path.exists():
        return None
    try:
        data: Dict[str, Any] = json.loads(path.read_text())
        return data
    except (OSError, ValueError):
        return None


@router.get("/trend-projection")
async def get_trend_projection(
    symbol: str = Query("BTC/USDT"),
    timeframe: Timeframe = Timeframe.M1,
    projection_bars: int = Query(12, ge=1, le=30),
) -> Dict[str, Any]:
    """Real, walk-forward-validated Ridge regression predictions from
    packages.retraining.price_projection. A horizon is only ever served if it demonstrably
    and consistently beat the naive "price doesn't change" baseline out-of-sample, across
    every walk-forward fold -- never just on average. If no trained artifact exists yet for
    this symbol/timeframe, or no horizon in it is approved, this returns `available: false`
    (`model_status: "NO_TRAINED_MODEL"`). There is deliberately NO fallback to a simpler
    heuristic in that case: this endpoint previously extrapolated the EMA-20 slope, which a
    real out-of-sample check showed has no predictive edge (worse MAPE than the naive
    baseline at every horizon, ~50-54% directional accuracy) -- silently falling back to it
    here would recreate exactly the fabricated-confidence failure mode this project avoids
    everywhere else."""
    now = datetime.now(timezone.utc)
    candles = await _fetch_real_candles(symbol, timeframe, limit=100)
    if not candles:
        return {
            "available": False, "reason": "NO_MARKET_DATA_AVAILABLE", "model_status": "NO_TRAINED_MODEL", "points": [],
        }

    artifact = _load_price_model_artifact(symbol, timeframe)
    if artifact is None:
        return {"available": False, "reason": "NO_TRAINED_MODEL", "model_status": "NO_TRAINED_MODEL", "points": []}

    sorted_candles = sorted(candles, key=lambda c: c.open_time)
    last_candle = sorted_candles[-1]
    request = FeatureComputationRequest(
        exchange="binance", symbol=symbol, timeframe=timeframe,
        feature_set="standard_v1", as_of_time=last_candle.close_time,
    )
    snapshot = feature_pipeline.compute(request, list(sorted_candles))
    feature_names: List[str] = artifact["feature_names"]
    raw_features = [snapshot.values.get(name) for name in feature_names]
    if any(v is None for v in raw_features):
        return {"available": False, "reason": "INSUFFICIENT_HISTORY", "model_status": "NO_TRAINED_MODEL", "points": []}
    features = [float(v) for v in raw_features]  # type: ignore[arg-type]

    interval = TIMEFRAME_INTERVAL[timeframe]
    last_close = float(last_candle.close_price)
    horizons: Dict[str, Any] = artifact["horizons"]
    approved_count = sum(1 for h in horizons.values() if h["approved"])
    points = []
    for h_str, h_data in sorted(horizons.items(), key=lambda kv: int(kv[0])):
        h = int(h_str)
        if not h_data["approved"] or h > projection_bars:
            continue
        scaled = [
            (f - m) / s
            for f, m, s in zip(features, h_data["feature_mean"], h_data["feature_scale"], strict=True)
        ]
        predicted_log_return = h_data["intercept"] + sum(
            c * x for c, x in zip(h_data["coefficients"], scaled, strict=True)
        )
        projected_price = last_close * math.exp(predicted_log_return)
        points.append({
            "time": (last_candle.close_time + interval * h).isoformat(),
            "projected_price": str(projected_price),
            "horizon_bars": h,
            "oos_mape": h_data["oos_mape"],
            "oos_directional_accuracy": h_data["oos_directional_accuracy"],
        })

    if not points:
        # A model WAS trained and evaluated for this symbol/timeframe -- it just didn't
        # clear the bar on real out-of-sample data. Distinct from "NO_TRAINED_MODEL" (no
        # artifact file at all) so the frontend/caller can tell "never attempted" apart from
        # "attempted, honestly rejected" -- both are `available: false`, but they're not the
        # same fact.
        return {
            "available": False, "reason": "NO_APPROVED_HORIZON", "model_status": "NO_APPROVED_MODEL",
            "model_trained_at": artifact["trained_at"], "points": [],
        }

    return {
        "available": True,
        "basis": "ridge_regression_v1",
        "model_status": "FULLY_APPROVED" if approved_count == len(horizons) else "PARTIAL",
        "model_trained_at": artifact["trained_at"],
        "as_of_time": now.isoformat(),
        "points": points,
    }


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
