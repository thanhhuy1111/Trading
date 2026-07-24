from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from packages.features.derivatives_models import DerivativesFeatureComputationRequest
from packages.features.derivatives_pipeline import derivatives_feature_pipeline
from packages.features.derivatives_registry import derivatives_feature_registry
from packages.features.models import FeatureComputationRequest, Timeframe
from packages.features.pipeline import feature_pipeline
from packages.features.registry import feature_registry
from packages.market_data import derivatives_history
from packages.market_data.adapters.binance import BinancePublicMarketDataProvider
from packages.market_data.adapters.binance_futures import BinancePublicFuturesDataProvider

router = APIRouter(prefix="/features", tags=["Features"])

_spot_provider = BinancePublicMarketDataProvider()
_derivatives_provider = BinancePublicFuturesDataProvider()


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


@router.get("/derivatives/definitions")
async def get_derivatives_feature_definitions() -> List[Dict[str, Any]]:
    defs = derivatives_feature_registry.list_definitions()
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


@router.get("/derivatives/snapshots/latest")
async def get_latest_derivatives_snapshot(symbol: str = Query("BTC/USDT")) -> Dict[str, Any]:
    """Live derivatives feature snapshot (funding-rate Z-score, open-interest ROC, futures-basis
    momentum) computed from the real, forward-accumulating snapshot history in
    `packages.market_data.derivatives_history`. Every call fetches a real snapshot, appends it
    to history (subject to the cache's own dedup interval), then computes features from
    whatever real history exists as of now -- honestly `WARMING_UP` until enough polls have
    landed, never a fabricated value."""
    now = datetime.now(timezone.utc)
    spot_reference_price: Optional[Decimal] = None
    try:
        prices = await _spot_provider.fetch_current_prices([symbol])
        spot_reference_price = prices.get(symbol)
    except Exception:  # noqa: BLE001 - basis just stays null; the snapshot is still usable
        spot_reference_price = None

    snapshot = await _derivatives_provider.fetch_snapshot(symbol, spot_reference_price=spot_reference_price)
    derivatives_history.append_snapshot(snapshot)
    history = derivatives_history.load_history(symbol, as_of=now)

    req = DerivativesFeatureComputationRequest(
        exchange=snapshot.exchange, symbol=symbol, feature_set="derivatives_v1", as_of_time=now,
    )
    feature_snapshot = derivatives_feature_pipeline.compute(req, history)
    return feature_snapshot.model_dump(mode="json")
