"""Phase 10 campaign API surface and public-data research analysis trigger."""

import asyncio
from concurrent.futures import Future
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from apps.api.chat_deps import enforce_analysis_rate_limit
from packages.common.config import settings
from packages.market_data.models import Timeframe
from packages.runtime.research_analysis import (
    PublicResearchAnalysisRuntime,
    ResearchAnalysisResult,
)

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
    as_of_time: Optional[datetime] = None
    runtime_mode: str = "RESEARCH_ONLY"
    agents: tuple[dict[str, object], ...] = ()
    debate: Optional[dict[str, object]] = None
    evidence: tuple[dict[str, object], ...] = ()
    verification: Optional[dict[str, object]] = None
    risk: Optional[dict[str, object]] = None


_ANALYSES: Dict[str, AnalysisView] = {}
_ANALYSIS_FINGERPRINTS: Dict[str, tuple[str, str]] = {}
_ANALYSES_INFLIGHT: Dict[str, Future[AnalysisView]] = {}
_ANALYSES_LOCK = Lock()
_MAX_ANALYSES = 1000
_RESEARCH_ANALYSIS_RUNTIME = PublicResearchAnalysisRuntime()


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


def get_research_analysis_runtime() -> PublicResearchAnalysisRuntime:
    return _RESEARCH_ANALYSIS_RUNTIME


@router.get("/market/{symbol}/overview")
def market_overview(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["MARKET_RUNTIME_NOT_CONFIGURED"],
        "data": None,
    }


@router.get("/market/{symbol}/candles")
def market_candles(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["CANDLE_RUNTIME_NOT_CONFIGURED"],
        "items": [],
    }


@router.get("/market/{symbol}/features")
def market_features(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["FEATURE_RUNTIME_NOT_CONFIGURED"],
        "items": [],
    }


@router.get("/market/{symbol}/derivatives")
def market_derivatives(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["DERIVATIVES_RUNTIME_NOT_CONFIGURED"],
        "items": [],
    }


@router.post(
    "/analysis/run",
    response_model=AnalysisView,
    status_code=202,
    dependencies=[Depends(enforce_analysis_rate_limit)],
)
async def run_analysis(
    request: AnalysisRunRequest,
    runtime: PublicResearchAnalysisRuntime = Depends(get_research_analysis_runtime),
) -> AnalysisView:
    try:
        timeframe = Timeframe(request.timeframe)
    except ValueError as exc:
        raise CampaignAPIError(
            422,
            "ANALYSIS_SCOPE_UNSUPPORTED",
            "The requested timeframe is not supported.",
        ) from exc
    if request.symbol not in runtime.supported_symbols:
        raise CampaignAPIError(
            422,
            "ANALYSIS_SCOPE_UNSUPPORTED",
            "Only registered research symbols are supported.",
        )
    analysis_id = request.request_id or str(uuid4())
    fingerprint = (request.symbol, request.timeframe)
    owns_request = False
    with _ANALYSES_LOCK:
        existing_fingerprint = _ANALYSIS_FINGERPRINTS.get(analysis_id)
        if existing_fingerprint is not None and existing_fingerprint != fingerprint:
            raise CampaignAPIError(
                409,
                "ANALYSIS_REQUEST_ID_CONFLICT",
                "The request_id is already bound to a different analysis scope.",
            )
        existing = _ANALYSES.get(analysis_id)
        if existing is not None:
            return existing
        inflight = _ANALYSES_INFLIGHT.get(analysis_id)
        if inflight is None:
            if len(_ANALYSIS_FINGERPRINTS) >= _MAX_ANALYSES:
                raise CampaignAPIError(
                    503,
                    "ANALYSIS_CAPACITY_REACHED",
                    "Analysis store capacity is reached.",
                )
            inflight = Future()
            _ANALYSES_INFLIGHT[analysis_id] = inflight
            _ANALYSIS_FINGERPRINTS[analysis_id] = fingerprint
            owns_request = True

    if not owns_request:
        return await asyncio.shield(asyncio.wrap_future(inflight))

    try:
        runtime_result = await runtime.analyze(
            analysis_id=analysis_id,
            symbol=request.symbol,
            timeframe=timeframe,
        )
        result = _analysis_view(
            analysis_id=analysis_id,
            symbol=request.symbol,
            timeframe=request.timeframe,
            runtime_result=runtime_result,
        )
    except BaseException as exc:
        with _ANALYSES_LOCK:
            _ANALYSES_INFLIGHT.pop(analysis_id, None)
            _ANALYSIS_FINGERPRINTS.pop(analysis_id, None)
            if not inflight.done():
                inflight.set_exception(exc)
        raise

    with _ANALYSES_LOCK:
        _ANALYSES[analysis_id] = result
        _ANALYSES_INFLIGHT.pop(analysis_id, None)
        if not inflight.done():
            inflight.set_result(result)
    return result


@router.get("/analysis/{analysis_id}", response_model=AnalysisView)
def get_analysis(analysis_id: str) -> AnalysisView:
    return _analysis_or_404(analysis_id)


@router.get("/analysis/{analysis_id}/agents")
def get_analysis_agents(analysis_id: str) -> dict[str, object]:
    analysis = _analysis_or_404(analysis_id)
    return {
        "analysis_id": analysis_id,
        "status": analysis.status,
        "reason_codes": analysis.reason_codes,
        "items": analysis.agents,
    }


@router.get("/analysis/{analysis_id}/debate")
def get_analysis_debate(analysis_id: str) -> dict[str, object]:
    analysis = _analysis_or_404(analysis_id)
    return {
        "analysis_id": analysis_id,
        "status": analysis.status,
        "reason_codes": analysis.reason_codes,
        "data": analysis.debate,
    }


@router.get("/analysis/{analysis_id}/evidence")
def get_analysis_evidence(analysis_id: str) -> dict[str, object]:
    analysis = _analysis_or_404(analysis_id)
    return {
        "analysis_id": analysis_id,
        "status": analysis.status,
        "reason_codes": analysis.reason_codes,
        "items": analysis.evidence,
    }


@router.get("/predictions")
def list_predictions() -> dict[str, object]:
    return {
        "items": [],
        "status": Availability.UNAVAILABLE,
        "reason_codes": ["PREDICTION_RUNTIME_NOT_CONFIGURED"],
    }


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str) -> dict[str, object]:
    raise CampaignAPIError(
        404,
        "PREDICTION_NOT_FOUND",
        "Prediction does not exist.",
    )


@router.get("/system/health")
def system_health() -> dict[str, object]:
    llm_configured = _RESEARCH_ANALYSIS_RUNTIME.llm_specialists_configured
    return {
        "status": "SAFE",
        "live_trading_enabled": settings.LIVE_TRADING_ENABLED,
        "private_exchange_api_enabled": settings.PRIVATE_EXCHANGE_API_ENABLED,
        "analysis_runtime": "RESEARCH_ONLY",
        "llm_specialist_runtime": (
            "CONFIGURED" if llm_configured else "NOT_CONFIGURED"
        ),
        "reason_codes": [
            "PUBLIC_MARKET_DATA_REQUIRED",
            "QUANTITATIVE_RUNTIME_NOT_BOUND",
            (
                "LLM_SPECIALIST_RUNTIME_CONFIGURED"
                if llm_configured
                else "LLM_SPECIALIST_RUNTIME_NOT_CONFIGURED"
            ),
        ],
    }


def _analysis_view(
    *,
    analysis_id: str,
    symbol: str,
    timeframe: str,
    runtime_result: ResearchAnalysisResult,
) -> AnalysisView:
    return AnalysisView(
        analysis_id=analysis_id,
        symbol=symbol,
        timeframe=timeframe,
        status=Availability(runtime_result.status),
        recommendation=runtime_result.recommendation,
        reason_codes=runtime_result.reason_codes,
        created_at=datetime.now(timezone.utc),
        as_of_time=runtime_result.as_of_time,
        agents=runtime_result.agents,
        evidence=runtime_result.evidence,
        debate=runtime_result.debate,
        verification=runtime_result.verification,
        risk=runtime_result.risk,
    )
