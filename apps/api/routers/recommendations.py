"""Recommendation / market-overview / strategy-evidence endpoints.

By default these call the exact same RecommendationService / EvidenceService /
ProposalStore singletons the chat tool registry uses (packages/chat_agent/tool_registry.py),
so a proposal_id returned from a scan here is retrievable via /recommendations/{proposal_id}
regardless of whether it was produced through the chat endpoint or this one directly.
Never calls ExecutionEngine; never returns a final order quantity.

Services are wired through FastAPI `Depends()` (not imported and called directly) so
tests can override them with in-memory test doubles via `app.dependency_overrides`
without any network access.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.api.dependencies import enforce_scan_rate_limit, require_advisor_api_key
from packages.recommendation.config import recommendation_config
from packages.recommendation.evidence_service import EvidenceService, evidence_service
from packages.recommendation.models import MarketOverview, RecommendationResult, StrategyEvidence, TradeProposal
from packages.recommendation.proposal_store import ProposalStore, proposal_store
from packages.recommendation.service import PIPELINE_STRATEGY_NAME, RecommendationService, recommendation_service

router = APIRouter(prefix="/api/v1", tags=["Recommendations"])


def get_recommendation_service() -> RecommendationService:
    return recommendation_service


def get_evidence_service() -> EvidenceService:
    return evidence_service


def get_proposal_store() -> ProposalStore:
    return proposal_store


class ScanRequest(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: list(recommendation_config.symbols_list))
    timeframes: List[str] = Field(default_factory=lambda: list(recommendation_config.timeframes_list))
    maximum_results: int = Field(default=3, ge=1, le=10)


@router.post(
    "/recommendations/scan",
    response_model=RecommendationResult,
    dependencies=[Depends(require_advisor_api_key), Depends(enforce_scan_rate_limit)],
)
async def scan_recommendations(
    request: ScanRequest, service: RecommendationService = Depends(get_recommendation_service)  # noqa: B008
) -> RecommendationResult:
    return await service.scan_trade_opportunities(
        symbols=request.symbols, timeframes=request.timeframes, max_results=request.maximum_results
    )


@router.get(
    "/recommendations/{proposal_id}",
    response_model=TradeProposal,
    dependencies=[Depends(require_advisor_api_key)],
)
async def get_recommendation(
    proposal_id: str, store: ProposalStore = Depends(get_proposal_store)  # noqa: B008
) -> TradeProposal:
    proposal = store.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.get(
    "/strategies/{strategy_version}/evidence",
    response_model=StrategyEvidence,
    dependencies=[Depends(require_advisor_api_key)],
)
async def get_strategy_evidence(
    strategy_version: str, service: EvidenceService = Depends(get_evidence_service)  # noqa: B008
) -> StrategyEvidence:
    return service.get_evidence(
        strategy_name=PIPELINE_STRATEGY_NAME,
        strategy_version=strategy_version,
        config_hash="",
        feature_version="standard_v1",
        now=datetime.now(timezone.utc),
    )


@router.get(
    "/market/overview",
    response_model=MarketOverview,
    dependencies=[Depends(require_advisor_api_key)],
)
async def get_market_overview(
    symbols: Optional[str] = Query(default=None, description="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT"),
    timeframes: Optional[str] = Query(default=None, description="Comma-separated timeframes, e.g. 15m,1h,4h"),
    service: RecommendationService = Depends(get_recommendation_service),  # noqa: B008
) -> MarketOverview:
    symbol_list = [s.strip().upper() for s in symbols.split(",")] if symbols else recommendation_config.symbols_list
    timeframe_list = [t.strip() for t in timeframes.split(",")] if timeframes else recommendation_config.timeframes_list
    return await service.get_market_overview(symbol_list, timeframe_list)
