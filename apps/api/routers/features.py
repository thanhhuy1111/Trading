from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Query
from pydantic import BaseModel

from packages.features.models import FeatureComputationRequest, Timeframe
from packages.features.pipeline import feature_pipeline
from packages.features.registry import feature_registry
from packages.market_data.adapters.binance import BinancePublicMarketDataProvider

router = APIRouter(prefix="/features", tags=["Features"])


class ComputeFeaturePayload(BaseModel):
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    feature_set: str = "standard_v1"


@router.get("/definitions")
async def get_feature_definitions() -> List[Dict[str, Any]]:
    defs = feature_registry.list_definitions()
    return [
        {
            "name": d.name,
            "version": d.version,
            "category": d.category,
            "description": d.description,
            "required_lookback": d.required_lookback,
            "output_type": d.output_type,
            "missing_policy": d.missing_policy,
        }
        for d in defs
    ]


@router.get("/sets")
async def get_feature_sets() -> List[Dict[str, Any]]:
    return [
        {
            "name": "standard_v1",
            "version": "1.0.0",
            "description": "Standard Technical Analysis Feature Set for Spot Alpha Strategy",
            "checksum": "sha256:4b9a8f1e2c3d4e5f",
            "features_count": len(feature_registry.list_definitions())
        }
    ]


@router.get("/snapshots/latest")
async def get_latest_snapshot(
    symbol: str = Query("BTC/USDT"),
    timeframe: str = Query("15m")
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    provider = BinancePublicMarketDataProvider()
    tf_enum = Timeframe.M15 if timeframe == "15m" else Timeframe.H1
    candles = await provider.fetch_candles(symbol, tf_enum, now - (tf_enum.value * 50), now, limit=50)

    req = FeatureComputationRequest(
        exchange="binance",
        symbol=symbol,
        timeframe=tf_enum,
        feature_set="standard_v1",
        as_of_time=now
    )
    snapshot = feature_pipeline.compute(req, candles)
    return snapshot.model_dump(mode="json")
