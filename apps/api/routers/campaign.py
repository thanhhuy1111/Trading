"""Phase 10 read-only campaign API surface and safe analysis trigger."""

from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from packages.common.config import settings

router = APIRouter(prefix="/api/v1", tags=["campaign"])


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class AnalysisRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = "BTC/USDT"
    timeframe: str = "4h"
    request_id: Optional[str] = Field(default=None, min_length=1)


class AnalysisView(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    symbol: str
    timeframe: str
    status: Availability
    recommendation: str = "NO_DECISION"
    reason_codes: tuple[str, ...]
    created_at: datetime
    agents: tuple[dict, ...] = ()
    debate: Optional[dict] = None
    evidence: tuple[dict, ...] = ()
    verification: Optional[dict] = None
    risk: Optional[dict] = None


_ANALYSES: Dict[str, AnalysisView] = {}
_ANALYSES_LOCK = Lock()
_MAX_ANALYSES = 1000


class CampaignAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _analysis_or_404(analysis_id: str) -> AnalysisView:
    analysis = _ANALYSES.get(analysis_id)
    if analysis is None:
        raise CampaignAPIError(
            404,
            "ANALYSIS_NOT_FOUND",
            "Analysis does not exist.",
        )
    return analysis


@router.get("/market/{symbol}/overview")
def market_overview(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["MARKET_RUNTIME_NOT_CONFIGURED"],
        "data": None,
    }


@router.get("/market/{symbol}/candles")
def market_candles(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["CANDLE_RUNTIME_NOT_CONFIGURED"],
        "items": [],
    }


@router.get("/market/{symbol}/features")
def market_features(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["FEATURE_RUNTIME_NOT_CONFIGURED"],
        "items": [],
    }


@router.get("/market/{symbol}/derivatives")
def market_derivatives(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["DERIVATIVES_RUNTIME_NOT_CONFIGURED"],
        "items": [],
    }


@router.post("/analysis/run", response_model=AnalysisView, status_code=202)
def run_analysis(request: AnalysisRunRequest) -> AnalysisView:
    if request.symbol != "BTC/USDT" or request.timeframe != "4h":
        raise CampaignAPIError(
            422,
            "ANALYSIS_SCOPE_UNSUPPORTED",
            "Only BTC/USDT 4h is supported.",
        )
    analysis_id = request.request_id or str(uuid4())
    with _ANALYSES_LOCK:
        existing = _ANALYSES.get(analysis_id)
        if existing is not None:
            return existing
        if len(_ANALYSES) >= _MAX_ANALYSES:
            raise CampaignAPIError(
                503,
                "ANALYSIS_CAPACITY_REACHED",
                "Analysis store capacity is reached.",
            )
        unavailable_agents = tuple(
            {
                "agent_name": agent_name,
                "status": "UNAVAILABLE",
                "reason_codes": ["ANALYSIS_RUNTIME_NOT_CONFIGURED"],
            }
            for agent_name in (
                "technical_agent",
                "derivatives_agent",
                "quantitative_agent",
            )
        )
        result = AnalysisView(
            analysis_id=analysis_id,
            symbol=request.symbol,
            timeframe=request.timeframe,
            status=Availability.UNAVAILABLE,
            reason_codes=("ANALYSIS_RUNTIME_NOT_CONFIGURED",),
            created_at=datetime.now(timezone.utc),
            agents=unavailable_agents,
            debate={
                "status": "FAILED",
                "reason_codes": ["UPSTREAM_AGENTS_UNAVAILABLE"],
                "turns": [],
            },
            verification={
                "decision": "REJECTED",
                "reason_codes": ["UPSTREAM_ANALYSIS_UNAVAILABLE"],
            },
            risk={
                "allow_trade": False,
                "approved_quantity": "0",
                "approved_notional": "0",
                "reason_codes": ["VERIFICATION_REJECTED"],
            },
        )
        _ANALYSES[analysis_id] = result
        return result


@router.get("/analysis/{analysis_id}", response_model=AnalysisView)
def get_analysis(analysis_id: str) -> AnalysisView:
    return _analysis_or_404(analysis_id)


@router.get("/analysis/{analysis_id}/agents")
def get_analysis_agents(analysis_id: str) -> dict:
    analysis = _analysis_or_404(analysis_id)
    return {
        "analysis_id": analysis_id,
        "status": analysis.status,
        "reason_codes": analysis.reason_codes,
        "items": analysis.agents,
    }


@router.get("/analysis/{analysis_id}/debate")
def get_analysis_debate(analysis_id: str) -> dict:
    analysis = _analysis_or_404(analysis_id)
    return {
        "analysis_id": analysis_id,
        "status": analysis.status,
        "reason_codes": analysis.reason_codes,
        "data": analysis.debate,
    }


@router.get("/analysis/{analysis_id}/evidence")
def get_analysis_evidence(analysis_id: str) -> dict:
    analysis = _analysis_or_404(analysis_id)
    return {
        "analysis_id": analysis_id,
        "status": analysis.status,
        "reason_codes": analysis.reason_codes,
        "items": analysis.evidence,
    }


@router.get("/predictions")
def list_predictions() -> dict:
    return {
        "items": [],
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["PREDICTION_RUNTIME_NOT_CONFIGURED"],
    }


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str) -> dict:
    raise CampaignAPIError(
        404,
        "PREDICTION_NOT_FOUND",
        "Prediction does not exist.",
    )


@router.get("/system/health")
def system_health() -> dict:
    return {
        "status": "SAFE",
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "private_exchange_api_enabled": settings.PRIVATE_EXCHANGE_API_ENABLED,
        "analysis_runtime": Availability.UNAVAILABLE,
        "reason_codes": ["ANALYSIS_RUNTIME_NOT_CONFIGURED"],
    }
