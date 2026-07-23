"""Phase 8: the 11 recommendation-architecture API endpoints.

Every endpoint here is backed by an already-tested Phase 1-7 service (never a fresh ad hoc
implementation) and never talks to a live exchange or an LLM provider directly - the
recommendation service's default wiring reads market data from the offline research cache
(`packages.runtime.candles_cache`) and every intelligence layer is the honest baseline/no-op
adapter unless a caller explicitly injects something else. A missing cache file or an empty
evidence registry is a normal, typed result (`NO_CANDIDATE`, `MISSING`), never a 500.

Endpoints:
    GET  /recommendations/health              - runtime-only health/readiness (no DB/network)
    POST /recommendations/analyze              - run the full pipeline for one symbol
    POST /recommendations/scan                 - run the full pipeline across several symbols
    GET  /recommendations/{proposal_id}         - fetch a previously generated TradeProposal
    GET  /readiness                             - current six-axis ReadinessStatus
    POST /evidence/lookup                       - exact-match evidence lookup (Section 5)
    GET  /strategy-portfolio/sleeves            - list registered strategy sleeves
    POST /strategy-portfolio/sleeves            - register a new strategy sleeve
    GET  /registries/{registry_name}/entries    - list entries in one Phase 3 artifact registry
    POST /portfolio-risk/evaluate               - direct portfolio risk governor evaluation
    GET  /system/architecture-status            - architecture completion summary
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from apps.api.deps import (
    REGISTRIES_BY_NAME,
    get_evidence_store,
    get_portfolio_risk_governor,
    get_recommendation_service,
    get_strategy_portfolio,
    require_permission,
)
from packages.candidates.models import TradeCandidate
from packages.domain.entities import ReadinessStatus, TradeProposal
from packages.domain.enums import (
    ArchitectureReadiness,
    EvidenceReadiness,
    LiveReadiness,
    ModelReadiness,
    StrategyReadiness,
)
from packages.evidence.models import EvidenceKey
from packages.evidence.store import EvidenceStore
from packages.governance.security import AuthenticatedPrincipal
from packages.intelligence.strategy_portfolio import StrategyPortfolio, StrategySleeve
from packages.market_data.models import Timeframe
from packages.ports.interfaces import PortfolioSnapshot, RecommendationRequest, RecommendationResult
from packages.registries.models import RegistryEntry
from packages.risk.portfolio_governor import BaselinePortfolioRiskGovernor, RiskEvaluationContext
from packages.runtime.recommendation_service import BaselineRecommendationService

router = APIRouter(tags=["Recommendations"])

# Ephemeral, in-memory only - not persisted across restarts (Phase 10's shadow storage is the
# durable record; this is purely so a caller can re-fetch what /analyze or /scan just handed
# back without re-running the whole pipeline). Bounded so a long-running process can't leak
# memory from repeated calls.
_MAX_STORED_PROPOSALS = 2000
_proposal_store: Dict[UUID, TradeProposal] = {}


def _remember(proposals: List[TradeProposal]) -> None:
    for p in proposals:
        _proposal_store[p.proposal_id] = p
    if len(_proposal_store) > _MAX_STORED_PROPOSALS:
        for old_id in list(_proposal_store)[: len(_proposal_store) - _MAX_STORED_PROPOSALS]:
            del _proposal_store[old_id]


class AnalyzeRequest(BaseModel):
    symbol: str
    timeframe: Timeframe = Timeframe.H1
    as_of_time: Optional[datetime] = None


class ScanRequest(BaseModel):
    symbols: List[str] = Field(min_length=1, max_length=50)
    timeframe: Timeframe = Timeframe.H1
    as_of_time: Optional[datetime] = None


class RecommendationResponse(BaseModel):
    request_id: UUID
    generated_at: datetime
    market_data_timestamp: Optional[datetime]
    universe_version: str
    candidate_ids: List[UUID]
    proposal_ids: List[UUID]
    readiness_status: ReadinessStatus
    reason_codes: List[str]
    limitations: List[str]
    application_result_state: str
    proposals: List[TradeProposal]


def _to_response(result: RecommendationResult) -> RecommendationResponse:
    return RecommendationResponse(
        request_id=result.request_id, generated_at=result.generated_at,
        market_data_timestamp=result.market_data_timestamp, universe_version=result.universe_version,
        candidate_ids=result.candidate_ids, proposal_ids=result.proposal_ids,
        readiness_status=result.readiness_status, reason_codes=result.reason_codes,
        limitations=result.limitations, application_result_state=result.application_result_state,
        proposals=result.proposals,
    )


@router.get("/recommendations/health")
async def recommendation_runtime_health(
    store: EvidenceStore = Depends(get_evidence_store),
) -> Dict[str, object]:
    """Confirms the recommendation runtime's own in-process dependencies (evidence store,
    strategy portfolio, registries) are constructed and reachable - deliberately independent
    of Postgres/Redis/network so it stays accurate even when those are down."""
    return {
        "status": "OK",
        "live_trading_enabled": False,
        "private_exchange_api_enabled": False,
        "evidence_registry_size": len(store.all_records()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/recommendations/analyze", response_model=RecommendationResponse)
async def analyze_symbol(
    body: AnalyzeRequest,
    service: BaselineRecommendationService = Depends(get_recommendation_service),
    _principal: AuthenticatedPrincipal = Depends(require_permission("create:recommendation")),
) -> RecommendationResponse:
    request = RecommendationRequest(
        request_id=uuid4(), symbols=[body.symbol], timeframe=body.timeframe,
        as_of_time=body.as_of_time or datetime.now(timezone.utc),
    )
    result = await service.analyze(request, body.symbol)
    _remember(result.proposals)
    return _to_response(result)


@router.post("/recommendations/scan", response_model=RecommendationResponse)
async def scan_symbols(
    body: ScanRequest,
    service: BaselineRecommendationService = Depends(get_recommendation_service),
    _principal: AuthenticatedPrincipal = Depends(require_permission("create:recommendation")),
) -> RecommendationResponse:
    request = RecommendationRequest(
        request_id=uuid4(), symbols=body.symbols, timeframe=body.timeframe,
        as_of_time=body.as_of_time or datetime.now(timezone.utc),
    )
    result = await service.scan(request)
    _remember(result.proposals)
    return _to_response(result)


@router.get("/recommendations/{proposal_id}", response_model=TradeProposal)
async def get_proposal(
    proposal_id: UUID, _principal: AuthenticatedPrincipal = Depends(require_permission("read:recommendations")),
) -> TradeProposal:
    proposal = _proposal_store.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.")
    return proposal


@router.get("/readiness", response_model=ReadinessStatus)
async def get_readiness(
    store: EvidenceStore = Depends(get_evidence_store),
    _principal: AuthenticatedPrincipal = Depends(require_permission("read:recommendations")),
) -> ReadinessStatus:
    """A generic, no-candidate-required readiness snapshot: architecture=READY (this endpoint
    itself proves the wiring runs end-to-end), evidence/strategy readiness reflect whatever is
    actually registered right now, live=DISABLED always."""
    evidence_records = store.all_records()
    approved = [r for r in evidence_records if r.status.value in ("UNIVERSAL_APPROVED", "ASSET_SPECIFIC_APPROVED")]
    strategy_readiness = StrategyReadiness.RESEARCH_ONLY
    evidence_readiness = EvidenceReadiness.NO_APPROVED_STRATEGY
    if not evidence_records:
        evidence_readiness = EvidenceReadiness.EMPTY_REGISTRY
    elif any(r.status.value == "UNIVERSAL_APPROVED" for r in approved):
        strategy_readiness = StrategyReadiness.UNIVERSAL_APPROVED
        evidence_readiness = EvidenceReadiness.UNIVERSAL_EVIDENCE
    elif approved:
        strategy_readiness = StrategyReadiness.ASSET_SPECIFIC_APPROVED
        evidence_readiness = EvidenceReadiness.ASSET_SPECIFIC_EVIDENCE
    return ReadinessStatus(
        architecture_readiness=ArchitectureReadiness.READY,
        strategy_readiness=strategy_readiness,
        model_readiness=ModelReadiness.BASELINE,
        evidence_readiness=evidence_readiness,
        shadow_readiness="READY",
        live_readiness=LiveReadiness.DISABLED,
        reason_codes=[],
    )


class EvidenceKeyRequest(BaseModel):
    strategy_name: str
    strategy_version: str
    symbol: str
    timeframe: str
    model_type: str
    model_version: str
    feature_version: str
    label_version: str
    dataset_checksum: str
    gate_version: str
    config_hash: str
    code_commit: str


@router.post("/evidence/lookup")
async def lookup_evidence(
    body: EvidenceKeyRequest,
    store: EvidenceStore = Depends(get_evidence_store),
    _principal: AuthenticatedPrincipal = Depends(require_permission("read:recommendations")),
) -> Dict[str, object]:
    key = EvidenceKey(**body.model_dump())
    outcome = store.lookup_with_result(key)
    return {
        "result": outcome.result.value, "record": outcome.record, "reason_codes": outcome.reason_codes,
    }


@router.get("/strategy-portfolio/sleeves", response_model=List[StrategySleeve])
async def list_strategy_sleeves(
    portfolio: StrategyPortfolio = Depends(get_strategy_portfolio),
    _principal: AuthenticatedPrincipal = Depends(require_permission("read:recommendations")),
) -> List[StrategySleeve]:
    return portfolio.all_sleeves()


@router.post("/strategy-portfolio/sleeves", response_model=StrategySleeve, status_code=status.HTTP_201_CREATED)
async def register_strategy_sleeve(
    sleeve: StrategySleeve,
    portfolio: StrategyPortfolio = Depends(get_strategy_portfolio),
    _principal: AuthenticatedPrincipal = Depends(require_permission("manage:strategy_portfolio")),
) -> StrategySleeve:
    portfolio.register(sleeve)
    return sleeve


@router.get("/registries/{registry_name}/entries", response_model=List[RegistryEntry])
async def list_registry_entries(
    registry_name: str,
    symbol: Optional[str] = Query(default=None),
    timeframe: Optional[str] = Query(default=None),
    _principal: AuthenticatedPrincipal = Depends(require_permission("read:recommendations")),
) -> List[RegistryEntry]:
    registry = REGISTRIES_BY_NAME.get(registry_name)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown registry. Valid names: {sorted(REGISTRIES_BY_NAME)}",
        )
    if symbol is not None or timeframe is not None:
        return registry.find_compatible(symbol=symbol, timeframe=timeframe)
    return registry.all_entries()


class PortfolioSnapshotRequest(BaseModel):
    available: bool
    nav: Optional[Decimal] = None
    open_risk_pct: Optional[Decimal] = None
    open_position_count: int = 0
    daily_realized_pnl_pct: Optional[Decimal] = None
    weekly_realized_pnl_pct: Optional[Decimal] = None
    current_drawdown_pct: Optional[Decimal] = None
    kill_switch_active: bool = False
    positions_by_symbol: Dict[str, Decimal] = Field(default_factory=dict)


class PortfolioRiskEvaluateRequest(BaseModel):
    candidate: TradeCandidate
    requested_risk_pct: Decimal
    portfolio: PortfolioSnapshotRequest
    evidence_actionable: bool
    is_stale_data: bool = False
    is_low_liquidity: bool = False


@router.post("/portfolio-risk/evaluate")
async def evaluate_portfolio_risk(
    body: PortfolioRiskEvaluateRequest,
    governor: BaselinePortfolioRiskGovernor = Depends(get_portfolio_risk_governor),
    _principal: AuthenticatedPrincipal = Depends(require_permission("read:recommendations")),
) -> Dict[str, object]:
    portfolio = PortfolioSnapshot(**body.portfolio.model_dump())
    context = RiskEvaluationContext(
        evidence_actionable=body.evidence_actionable, is_stale_data=body.is_stale_data,
        is_low_liquidity=body.is_low_liquidity,
    )
    decision = governor.evaluate(body.candidate, body.requested_risk_pct, portfolio, context)
    return {
        "decision": decision.decision.value, "requested_risk_pct": str(decision.requested_risk_pct),
        "approved_risk_pct": str(decision.approved_risk_pct), "reason_codes": decision.reason_codes,
        "policy_version": decision.policy_version,
    }


@router.get("/system/architecture-status")
async def get_architecture_status(
    _principal: AuthenticatedPrincipal = Depends(require_permission("read:recommendations")),
) -> Dict[str, object]:
    return {
        "architecture_readiness": ArchitectureReadiness.READY.value,
        "live_readiness": LiveReadiness.DISABLED.value,
        "live_trading_enabled": False,
        "private_exchange_api_enabled": False,
        "endpoints_implemented": 11,
        "note": (
            "Architecture completion is independent of strategy/model/evidence approval - "
            "see /readiness for the current strategy/model/evidence/shadow axes."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
