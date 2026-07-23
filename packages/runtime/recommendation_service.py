"""Phase 7: Recommendation Runtime.

The single end-to-end orchestrator that wires every service built in Phases 1-6 into one
flow: candles -> data quality -> features -> regime -> strategy routing -> agents ->
candidate -> meta-label -> market context (advisory only) -> evidence lookup -> ranking ->
correlation -> portfolio risk -> TradeProposal (or an explicit non-trade
`ApplicationResultState`). It never fabricates a proposal, and it never lets the LLM/market
context layer override a risk or evidence decision (this module has no import path into
`packages.llm`'s provider clients, and `MarketContextAssessment.risk_adjustment` is read here
only for the reason_codes it carries — never as an input to `PortfolioRiskPolicy` or the
ranking score).

Every dependency (candles, portfolio snapshot, the intelligence services) is constructor-
injected, so the whole flow is testable offline with fixture candles and fake services — this
module never reaches for a live network client itself.

State mapping (the 11 `ApplicationResultState` values), each reachable and non-overlapping:
    NO_CANDIDATE        - no candles at all, or the Checkpoint 2 pipeline found no tradeable
                           signal (router said no-trade, or no agent produced a trade intent).
    DATA_QUALITY_FAILED - the dataset was rejected for severe gaps, or there is no candle at
                           the requested decision time.
    STALE_DATA          - the freshest candle is older than the configured staleness bound.
    NO_TRADE            - a candidate was built but the meta-label service actively rejected it.
    MODEL_NOT_AVAILABLE - `config.require_trained_model=True` and no trained model artifact is
                           registered/loadable/feature-complete for this candidate.
    STRATEGY_NOT_APPROVED - the exact-match evidence record for this strategy/symbol/timeframe
                           was explicitly REJECTED or DISABLED (evaluated and turned down, not
                           merely unproven).
    INSUFFICIENT_EVIDENCE - `config.require_actionable_evidence=True` and no APPROVED evidence
                           record exists (covers MISSING/MISMATCH/STALE/RESEARCH_ONLY/DEGRADED).
    RESEARCH_PROPOSAL   - the default, permissive path: a proposal IS produced even without
                           approved evidence (so Phase 10 shadow mode always has something to
                           evaluate), just flagged non-actionable for real capital.
    RISK_LIMIT_EXCEEDED - evidence was actionable, but the portfolio risk governor rejected or
                           halted (for a reason other than missing portfolio state).
    SYSTEM_DEGRADED     - portfolio state was unavailable, or an unexpected internal error was
                           caught (never silently swallowed - always surfaced in reason_codes).
    APPROVED_PROPOSAL   - evidence was actionable and the portfolio risk governor approved or
                           reduced the requested risk.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, List, Optional
from uuid import UUID

from packages.agents.strategy_config import StrategyConfig, default_strategy_config
from packages.domain.entities import (
    ModelPrediction,
    RankingResult,
    ReadinessStatus,
    TradeCandidate,
    TradeProposal,
    stable_checksum,
)
from packages.domain.enums import (
    ApplicationResultState,
    ArchitectureReadiness,
    EvidenceReadiness,
    LiveReadiness,
    MetaLabelDecision,
    ModelReadiness,
    StrategyReadiness,
)
from packages.evidence.models import EvidenceKey, EvidenceStatus
from packages.evidence.store import EvidenceStore, evidence_store
from packages.governance.candidate_pipeline import run_candidate_pipeline
from packages.intelligence.correlation import BaselineCorrelationService
from packages.intelligence.market_context import BaselineMarketContextService
from packages.intelligence.meta_label import PassThroughMetaLabelService
from packages.intelligence.ranking import BaselineRankingService, RankingInput
from packages.intelligence.strategy_portfolio import StrategyPortfolio
from packages.market_data.historical_quality import TIMEFRAME_INTERVAL
from packages.market_data.models import Candle, Timeframe
from packages.ports.interfaces import MarketContextService as MarketContextServicePort
from packages.ports.interfaces import MetaLabelService as MetaLabelServicePort
from packages.ports.interfaces import PortfolioSnapshot, RecommendationRequest, RecommendationResult
from packages.risk.portfolio_governor import BaselinePortfolioRiskGovernor, RiskEvaluationContext

CandlesProvider = Callable[[str, Timeframe, datetime, datetime], List[Candle]]
IntWindowCandlesProvider = Callable[[str, Timeframe, datetime, int], List[Candle]]
PortfolioSnapshotProvider = Callable[[], PortfolioSnapshot]


def _window_bars_adapter(provider: CandlesProvider) -> IntWindowCandlesProvider:
    """`BaselineCorrelationService` (Phase 4.4) takes a `(symbol, timeframe, as_of_time,
    window_bars: int)` candles provider; this runtime's own `CandlesProvider` takes an
    explicit `(start, end)` range instead, matching `run_candidate_pipeline`'s convention.
    Adapts the latter to the former rather than forcing every caller to implement both
    shapes."""

    def _adapted(symbol: str, timeframe: Timeframe, as_of_time: datetime, window_bars: int) -> List[Candle]:
        interval = TIMEFRAME_INTERVAL.get(timeframe, timedelta(hours=1))
        start = as_of_time - interval * window_bars
        return provider(symbol, timeframe, start, as_of_time)

    return _adapted


GATE_VERSION = "gate_v1"
CODE_COMMIT = "n/a"  # populated by CI in a real deployment; not required for this task
DATASET_CHECKSUM_BASELINE = "n/a"  # no trained-model evidence dataset in this architecture task

_UNAVAILABLE_MODEL_REASONS = {"TRAINED_MODEL_NOT_AVAILABLE", "MODEL_ARTIFACT_UNREADABLE", "REQUIRED_FEATURE_MISSING"}
_REJECTED_EVIDENCE_STATUSES = (EvidenceStatus.REJECTED, EvidenceStatus.DISABLED)
_ACTIONABLE_EVIDENCE_STATUSES = (EvidenceStatus.UNIVERSAL_APPROVED, EvidenceStatus.ASSET_SPECIFIC_APPROVED)


@dataclass
class RecommendationServiceConfig:
    strategy_config: StrategyConfig = field(default_factory=lambda: default_strategy_config)
    strategy_name: str = "checkpoint2_pipeline_demo"
    strategy_version: str = "1.0.0"
    feature_lookback_bars: int = 250
    staleness_threshold: Optional[timedelta] = None
    requested_risk_pct: Decimal = Decimal("0.25")
    require_trained_model: bool = False
    require_actionable_evidence: bool = False


@dataclass
class _SymbolOutcome:
    state: ApplicationResultState
    reason_codes: List[str]
    limitations: List[str]
    candidate_id: Optional[UUID] = None
    proposal: Optional[TradeProposal] = None


class BaselineRecommendationService:
    """The default, dependency-free wiring: PassThroughMetaLabelService (never a fabricated
    probability), BaselineMarketContextService (every LLM agent disabled), the global
    `evidence_store` (exact-match only), BaselineRankingService, BaselineCorrelationService,
    an empty StrategyPortfolio, and BaselinePortfolioRiskGovernor. Every argument can be
    overridden so a caller can swap in a trained model, a curated strategy portfolio, or a
    real portfolio snapshot provider without touching this class."""

    def __init__(
        self,
        candles_provider: CandlesProvider,
        meta_label_service: Optional[MetaLabelServicePort] = None,
        market_context_service: Optional[MarketContextServicePort] = None,
        evidence_service: Optional[EvidenceStore] = None,
        ranking_service: Optional[BaselineRankingService] = None,
        correlation_service: Optional[BaselineCorrelationService] = None,
        strategy_portfolio: Optional[StrategyPortfolio] = None,
        portfolio_risk_governor: Optional[BaselinePortfolioRiskGovernor] = None,
        portfolio_snapshot_provider: Optional[PortfolioSnapshotProvider] = None,
        config: Optional[RecommendationServiceConfig] = None,
    ) -> None:
        self.candles_provider = candles_provider
        self.meta_label_service = meta_label_service or PassThroughMetaLabelService()
        self.market_context_service = market_context_service or BaselineMarketContextService()
        self.evidence_service = evidence_service or evidence_store
        self.ranking_service = ranking_service or BaselineRankingService()
        self.correlation_service = correlation_service or BaselineCorrelationService(
            candles_provider=_window_bars_adapter(candles_provider),
        )
        self.strategy_portfolio = strategy_portfolio or StrategyPortfolio()
        self.portfolio_risk_governor = portfolio_risk_governor or BaselinePortfolioRiskGovernor()
        self.portfolio_snapshot_provider = portfolio_snapshot_provider or (lambda: PortfolioSnapshot(available=False))
        self.config = config or RecommendationServiceConfig()

    async def scan(self, request: RecommendationRequest) -> RecommendationResult:
        """Runs `analyze` independently for every symbol in the request; a failure or non-
        trade result on one symbol never blocks the others. The top-level
        `application_result_state` is a coarse aggregate (best state seen across symbols) -
        the authoritative per-symbol state lives on each `TradeProposal`, and per-symbol
        rejection reasons are folded into `reason_codes`."""
        candidate_ids: List[UUID] = []
        proposals: List[TradeProposal] = []
        reason_codes: List[str] = []
        limitations: List[str] = []
        best_state = ApplicationResultState.NO_CANDIDATE

        for symbol in request.symbols:
            outcome = await self._analyze_one(request, symbol)
            if outcome.candidate_id is not None:
                candidate_ids.append(outcome.candidate_id)
            if outcome.proposal is not None:
                proposals.append(outcome.proposal)
            reason_codes.extend(f"{symbol}:{code}" for code in outcome.reason_codes)
            limitations.extend(outcome.limitations)
            best_state = _better(best_state, outcome.state)

        return RecommendationResult(
            request_id=request.request_id,
            generated_at=request.generated_at,
            market_data_timestamp=request.as_of_time,
            universe_version=stable_checksum({"symbols": sorted(request.symbols)}),
            candidate_ids=candidate_ids,
            proposal_ids=[p.proposal_id for p in proposals],
            readiness_status=self._readiness_status(reason_codes),
            reason_codes=reason_codes,
            limitations=limitations,
            application_result_state=best_state.value,
            proposals=proposals,
        )

    async def analyze(self, request: RecommendationRequest, symbol: str) -> RecommendationResult:
        outcome = await self._analyze_one(request, symbol)
        proposals = [outcome.proposal] if outcome.proposal is not None else []
        return RecommendationResult(
            request_id=request.request_id,
            generated_at=request.generated_at,
            market_data_timestamp=request.as_of_time,
            universe_version=stable_checksum({"symbols": [symbol]}),
            candidate_ids=[outcome.candidate_id] if outcome.candidate_id else [],
            proposal_ids=[p.proposal_id for p in proposals],
            readiness_status=self._readiness_status(outcome.reason_codes),
            reason_codes=outcome.reason_codes,
            limitations=outcome.limitations,
            application_result_state=outcome.state.value,
            proposals=proposals,
        )

    async def _analyze_one(self, request: RecommendationRequest, symbol: str) -> _SymbolOutcome:
        try:
            return await self._analyze_one_unsafe(request, symbol)
        except Exception as exc:  # noqa: BLE001 - deliberately caught and surfaced, never swallowed
            return _SymbolOutcome(
                state=ApplicationResultState.SYSTEM_DEGRADED,
                reason_codes=[f"UNEXPECTED_ERROR:{type(exc).__name__}:{exc}"],
                limitations=["An unexpected internal error occurred; see reason_codes."],
            )

    async def _analyze_one_unsafe(self, request: RecommendationRequest, symbol: str) -> _SymbolOutcome:
        interval = TIMEFRAME_INTERVAL.get(request.timeframe, timedelta(hours=1))
        lookback_bars = self.config.feature_lookback_bars + 50
        start = request.as_of_time - interval * lookback_bars
        raw_candles = self.candles_provider(symbol, request.timeframe, start, request.as_of_time)
        if not raw_candles:
            return _SymbolOutcome(
                state=ApplicationResultState.NO_CANDIDATE, reason_codes=["NO_MARKET_DATA_AVAILABLE"], limitations=[],
            )

        pipeline_outcome = await run_candidate_pipeline(
            raw_candles=raw_candles, timeframe=request.timeframe, as_of_time=request.as_of_time, symbol=symbol,
            strategy_config=self.config.strategy_config, strategy_name=self.config.strategy_name,
            strategy_version=self.config.strategy_version, now=request.generated_at,
            staleness_threshold=self.config.staleness_threshold,
        )
        if pipeline_outcome.candidate is None:
            return _SymbolOutcome(
                state=_state_for_pipeline_rejection(pipeline_outcome.rejected_reason),
                reason_codes=[pipeline_outcome.rejected_reason or "NO_TRADEABLE_SIGNAL"],
                limitations=[],
            )
        candidate = pipeline_outcome.candidate

        prediction = await self.meta_label_service.predict(candidate)
        if self.config.require_trained_model and any(
            code in _UNAVAILABLE_MODEL_REASONS for code in prediction.reason_codes
        ):
            return _SymbolOutcome(
                state=ApplicationResultState.MODEL_NOT_AVAILABLE, reason_codes=list(prediction.reason_codes),
                limitations=[], candidate_id=candidate.candidate_id,
            )
        if prediction.decision == MetaLabelDecision.REJECT:
            return _SymbolOutcome(
                state=ApplicationResultState.NO_TRADE, reason_codes=["META_LABEL_REJECTED_CANDIDATE"],
                limitations=[], candidate_id=candidate.candidate_id,
            )

        context_assessments = await self.market_context_service.assess(symbol, request.as_of_time)
        limitations = [
            f"{a.agent_name}:{','.join(a.reason_codes)}" for a in context_assessments if a.reason_codes
        ]

        evidence_key = EvidenceKey(
            strategy_name=candidate.strategy_name, strategy_version=candidate.strategy_version,
            symbol=candidate.symbol, timeframe=candidate.timeframe, model_type=prediction.model_type.value,
            model_version=prediction.model_version, feature_version=prediction.feature_version,
            label_version=prediction.label_version, dataset_checksum=DATASET_CHECKSUM_BASELINE,
            gate_version=GATE_VERSION, config_hash=candidate.strategy_config_hash, code_commit=CODE_COMMIT,
        )
        evidence_outcome = self.evidence_service.lookup_with_result(evidence_key, as_of=request.as_of_time)
        record = evidence_outcome.record

        if record is not None and record.status in _REJECTED_EVIDENCE_STATUSES:
            return _SymbolOutcome(
                state=ApplicationResultState.STRATEGY_NOT_APPROVED,
                reason_codes=[f"EVIDENCE_STATUS_{record.status.value}"], limitations=limitations,
                candidate_id=candidate.candidate_id,
            )

        evidence_actionable = record is not None and record.status in _ACTIONABLE_EVIDENCE_STATUSES
        evidence_status_label = record.status.value if record is not None else evidence_outcome.result.value

        if not evidence_actionable and self.config.require_actionable_evidence:
            return _SymbolOutcome(
                state=ApplicationResultState.INSUFFICIENT_EVIDENCE,
                reason_codes=[f"EVIDENCE_NOT_ACTIONABLE:{evidence_status_label}", *evidence_outcome.reason_codes],
                limitations=limitations, candidate_id=candidate.candidate_id,
            )

        cost_bps = candidate.estimated_fee_bps + candidate.estimated_spread_bps + candidate.estimated_slippage_bps
        ranking_result = self.ranking_service.rank([RankingInput(
            candidate_id=candidate.candidate_id, symbol=candidate.symbol, expected_net_edge_bps=None,
            calibrated_probability=prediction.probability, evidence=record, liquidity_score=Decimal("0.5"),
            data_freshness_score=Decimal("1.0"), cost_bps=cost_bps, correlated_exposure_score=Decimal("0"),
            risk_score=Decimal("0.1"),
        )])[0]

        # Correlation and strategy-portfolio are consulted for every proposal (research or
        # approved) so a research recommendation still reflects "what would correlation/
        # sleeve authorization/portfolio risk have said" - informational for a research
        # proposal (no real capital is requested), binding for an approved one.
        portfolio_snapshot = self.portfolio_snapshot_provider()
        correlation_snapshots = [
            self.correlation_service.snapshot(symbol, held_symbol, request.timeframe, request.as_of_time)
            for held_symbol in portfolio_snapshot.positions_by_symbol
            if held_symbol != symbol
        ]
        sleeve_reason_codes = _strategy_sleeve_reason_codes(self.strategy_portfolio, candidate)
        advisory_risk_decision = self.portfolio_risk_governor.evaluate(
            candidate, self.config.requested_risk_pct, portfolio_snapshot,
            RiskEvaluationContext(evidence_actionable=evidence_actionable, correlation_snapshots=correlation_snapshots),
        )

        if not evidence_actionable:
            proposal = self._build_proposal(
                candidate, prediction, ranking_result, evidence_status_label,
                ApplicationResultState.RESEARCH_PROPOSAL, approved_risk_pct=None,
            )
            return _SymbolOutcome(
                state=ApplicationResultState.RESEARCH_PROPOSAL,
                reason_codes=[
                    f"EVIDENCE_NOT_ACTIONABLE:{evidence_status_label}", *evidence_outcome.reason_codes,
                    *sleeve_reason_codes,
                    *[f"ADVISORY_RISK:{code}" for code in advisory_risk_decision.reason_codes],
                ],
                limitations=limitations, candidate_id=candidate.candidate_id, proposal=proposal,
            )

        risk_decision = advisory_risk_decision  # binding once evidence is actionable

        if risk_decision.decision.value == "HALT":
            state = (
                ApplicationResultState.SYSTEM_DEGRADED
                if "PORTFOLIO_STATE_UNAVAILABLE" in risk_decision.reason_codes
                else ApplicationResultState.RISK_LIMIT_EXCEEDED
            )
            return _SymbolOutcome(
                state=state, reason_codes=list(risk_decision.reason_codes), limitations=limitations,
                candidate_id=candidate.candidate_id,
            )
        if risk_decision.decision.value == "REJECT":
            return _SymbolOutcome(
                state=ApplicationResultState.RISK_LIMIT_EXCEEDED, reason_codes=list(risk_decision.reason_codes),
                limitations=limitations, candidate_id=candidate.candidate_id,
            )

        proposal = self._build_proposal(
            candidate, prediction, ranking_result, evidence_status_label,
            ApplicationResultState.APPROVED_PROPOSAL, approved_risk_pct=risk_decision.approved_risk_pct,
        )
        return _SymbolOutcome(
            state=ApplicationResultState.APPROVED_PROPOSAL,
            reason_codes=[*risk_decision.reason_codes, *sleeve_reason_codes],
            limitations=limitations, candidate_id=candidate.candidate_id, proposal=proposal,
        )

    def _build_proposal(
        self,
        candidate: TradeCandidate,
        prediction: ModelPrediction,
        ranking_result: RankingResult,
        evidence_status_label: str,
        state: ApplicationResultState,
        approved_risk_pct: Optional[Decimal],
    ) -> TradeProposal:
        return TradeProposal(
            candidate_id=candidate.candidate_id, symbol=candidate.symbol, timeframe=candidate.timeframe,
            direction=candidate.direction, entry_reference=candidate.entry_reference,
            stop_loss=candidate.stop_loss, take_profit=candidate.take_profit,
            risk_reward_ratio=candidate.risk_reward_ratio, estimated_fee_bps=candidate.estimated_fee_bps,
            estimated_spread_bps=candidate.estimated_spread_bps,
            estimated_slippage_bps=candidate.estimated_slippage_bps,
            expected_net_return_bps=ranking_result.expected_net_edge_bps,
            calibrated_probability=prediction.probability, strategy_version=candidate.strategy_version,
            model_version=prediction.model_version, evidence_status=evidence_status_label,
            ranking_score=ranking_result.ranking_score, approved_risk_pct=approved_risk_pct,
            proposal_expiry=candidate.decision_timestamp + TIMEFRAME_INTERVAL.get(
                Timeframe(candidate.timeframe), timedelta(hours=1),
            ),
            reason_codes=list(ranking_result.reason_codes), application_result_state=state,
        )

    def _readiness_status(self, reason_codes: List[str]) -> ReadinessStatus:
        strategy_readiness = StrategyReadiness.RESEARCH_ONLY
        evidence_readiness = EvidenceReadiness.NO_APPROVED_STRATEGY
        if any("UNIVERSAL_APPROVED" in c for c in reason_codes):
            strategy_readiness = StrategyReadiness.UNIVERSAL_APPROVED
            evidence_readiness = EvidenceReadiness.UNIVERSAL_EVIDENCE
        elif any("ASSET_SPECIFIC_APPROVED" in c for c in reason_codes):
            strategy_readiness = StrategyReadiness.ASSET_SPECIFIC_APPROVED
            evidence_readiness = EvidenceReadiness.ASSET_SPECIFIC_EVIDENCE
        model_readiness = (
            ModelReadiness.BASELINE if isinstance(self.meta_label_service, PassThroughMetaLabelService)
            else ModelReadiness.RESEARCH_ONLY
        )
        return ReadinessStatus(
            architecture_readiness=ArchitectureReadiness.READY,
            strategy_readiness=strategy_readiness,
            model_readiness=model_readiness,
            evidence_readiness=evidence_readiness,
            shadow_readiness="READY",
            live_readiness=LiveReadiness.DISABLED,
            reason_codes=[],
            code_commit=CODE_COMMIT,
        )


def _strategy_sleeve_reason_codes(strategy_portfolio: StrategyPortfolio, candidate: TradeCandidate) -> List[str]:
    """Informational only - the strategy portfolio never blocks a proposal in this baseline
    (an empty/uncurated portfolio is the expected default state, not an error); it just records
    whether a sleeve exists and whether it's evidence-approved, for the caller/shadow record to
    see."""
    eligible = strategy_portfolio.eligible_sleeves(candidate.symbol, candidate.timeframe, candidate.market_regime)
    if not eligible:
        return ["NO_STRATEGY_SLEEVE_REGISTERED"]
    approved = strategy_portfolio.approved_sleeves(candidate.symbol, candidate.timeframe, candidate.market_regime)
    if approved:
        return ["STRATEGY_SLEEVE_APPROVED_ELIGIBLE"]
    return ["STRATEGY_SLEEVE_RESEARCH_ONLY"]


def _state_for_pipeline_rejection(reason: Optional[str]) -> ApplicationResultState:
    if reason == "DATASET_REJECTED_SEVERE_GAPS_OR_EMPTY":
        return ApplicationResultState.DATA_QUALITY_FAILED
    if reason == "NO_CANDLE_AT_DECISION_TIME":
        return ApplicationResultState.DATA_QUALITY_FAILED
    if reason == "STALE_DATA":
        return ApplicationResultState.STALE_DATA
    return ApplicationResultState.NO_CANDIDATE


_STATE_RANK = [
    ApplicationResultState.NO_CANDIDATE,
    ApplicationResultState.DATA_QUALITY_FAILED,
    ApplicationResultState.STALE_DATA,
    ApplicationResultState.SYSTEM_DEGRADED,
    ApplicationResultState.MODEL_NOT_AVAILABLE,
    ApplicationResultState.STRATEGY_NOT_APPROVED,
    ApplicationResultState.NO_TRADE,
    ApplicationResultState.INSUFFICIENT_EVIDENCE,
    ApplicationResultState.RISK_LIMIT_EXCEEDED,
    ApplicationResultState.RESEARCH_PROPOSAL,
    ApplicationResultState.APPROVED_PROPOSAL,
]


def _better(a: ApplicationResultState, b: ApplicationResultState) -> ApplicationResultState:
    """Deterministic aggregate ordering for `scan()`'s coarse top-level state: the more
    "there is something actionable here" a state is, the higher it ranks."""
    return b if _STATE_RANK.index(b) > _STATE_RANK.index(a) else a
