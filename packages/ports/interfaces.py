"""Service interfaces (Phase 2). Every port is a `typing.Protocol` — structural typing, so a
concrete adapter (baseline, LLM-backed, DB-backed, ...) doesn't need to inherit from anything
here, it just needs to match the method signatures. This keeps the domain/application layers
free of concrete infrastructure imports (Section 7: "do not instantiate external clients deep
inside business logic").

Each Protocol documents:
  - typed input / output (via domain entities or the lightweight request/response types below)
  - timeout policy, where the port has an external dependency
  - whether the port is expected to be deterministic

Concrete implementations live under packages/intelligence/, packages/risk/, packages/llm/,
packages/shadow/, packages/monitoring/, packages/retraining/ — this module only declares the
contracts.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol
from uuid import UUID

from packages.domain.entities import (
    CorrelationSnapshot,
    DriftAssessment,
    EvidenceRecord,
    MarketContextAssessment,
    MarketDataset,
    ModelPrediction,
    PortfolioRiskDecision,
    RankingResult,
    ReadinessStatus,
    ShadowOutcome,
    ShadowProposal,
    TradeCandidate,
    TradeProposal,
)
from packages.domain.enums import EvidenceLookupResult
from packages.evidence.models import EvidenceKey
from packages.market_data.historical_quality import DatasetQualityReport
from packages.market_data.models import Candle, Timeframe
from packages.universe.models import UniverseSnapshot

# --- Lightweight request/response shapes not already covered by a domain entity ---


@dataclass(frozen=True)
class RecommendationRequest:
    request_id: UUID
    symbols: List[str]
    timeframe: Timeframe
    as_of_time: datetime
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RecommendationResult:
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
    proposals: List[TradeProposal] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceLookupOutcome:
    result: EvidenceLookupResult
    record: Optional[EvidenceRecord]
    reason_codes: List[str]


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Minimal, explicit portfolio state a PortfolioRiskService needs. `available` is False
    when the caller couldn't load real portfolio state — the risk service must treat that as
    conservative (reject/halt), never as "no risk"."""

    available: bool
    nav: Optional[Decimal] = None
    open_risk_pct: Optional[Decimal] = None
    open_position_count: int = 0
    daily_realized_pnl_pct: Optional[Decimal] = None
    weekly_realized_pnl_pct: Optional[Decimal] = None
    current_drawdown_pct: Optional[Decimal] = None
    kill_switch_active: bool = False
    positions_by_symbol: Dict[str, Decimal] = field(default_factory=dict)


# --- Universe & market data ---


class UniverseService(Protocol):
    """Deterministic given its inputs; live refresh (network) is a separate, explicit,
    opt-in call — see packages/universe/live_source.py. No timeout applies to the pure
    `current_snapshot` read; `refresh` has one (network-bound)."""

    def current_snapshot(self) -> Optional[UniverseSnapshot]: ...

    async def refresh(self, timeout_seconds: float = 20.0) -> UniverseSnapshot: ...


class MarketDataService(Protocol):
    """Timeout policy: network calls (live_source-style fetches) must bound at
    DEFAULT_TIMEOUT_SECONDS. Cache reads are synchronous/instant and raise
    DataUnavailableError rather than blocking."""

    DEFAULT_TIMEOUT_SECONDS: float = 20.0

    async def load_closed_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime,
    ) -> List[Candle]: ...

    def dataset_metadata(self, symbol: str, timeframe: Timeframe) -> Optional[MarketDataset]: ...


class DataQualityService(Protocol):
    """Pure/deterministic — packages.market_data.historical_quality.validate_historical_series
    wrapped behind this port."""

    def validate(
        self, candles: List[Candle], timeframe: Timeframe, as_of: datetime,
    ) -> "tuple[List[Candle], DatasetQualityReport]": ...


class FeatureService(Protocol):
    """Pure/deterministic given (candles, as_of_time) — no external dependency, no timeout."""

    def compute(self, symbol: str, timeframe: Timeframe, candles: List[Candle], as_of_time: datetime) -> Any: ...


class RegimeService(Protocol):
    """Pure/deterministic — wraps packages.agents.regime.MarketRegimeAgent."""

    def classify(self, symbol: str, timeframe: Timeframe, feature_snapshot: Any, as_of_time: datetime) -> Any: ...


class StrategyRouterPort(Protocol):
    """Pure/deterministic — wraps packages.governance.strategy_router.route."""

    def route(self, regime: Any) -> Any: ...


class AgentService(Protocol):
    """Runs the allowed rule-based agents for one decision point. Pure/deterministic given
    identical inputs (same guarantee packages.governance.decision_service.decide already
    provides — no LLM, no randomness)."""

    async def evaluate(
        self, symbol: str, timeframe: Timeframe, as_of_time: datetime, allowed_strategy_types: Any,
    ) -> Any: ...


class CandidateService(Protocol):
    """Builds a TradeCandidate from a decision result. Pure — packages.candidates.builder."""

    def build(
        self, decision: Any, session_id: UUID, strategy_name: str, strategy_version: str,
    ) -> Optional[TradeCandidate]: ...


# --- Intelligence layer (Phase 4/9) ---


class MetaLabelService(Protocol):
    """model_version="n/a" + probability=None + decision=DEFER_TO_EXISTING_RULES is the
    required, honest baseline response (PassThroughMetaLabelService) — never a fabricated
    probability. Deterministic; no external dependency for the baseline/LR/tree
    implementations (all are local inference, not API calls)."""

    async def predict(self, candidate: TradeCandidate) -> ModelPrediction: ...


class MarketContextService(Protocol):
    """Aggregates News/Macro/Sentiment/RiskCritic agents (Phase 9). Each underlying agent has
    its own timeout policy (see packages.llm.framework); this port's own timeout is the sum
    bound across all agents queried. status=NOT_AVAILABLE with every no-op adapter — the
    runtime must work with this entire service disabled."""

    DEFAULT_TIMEOUT_SECONDS: float = 10.0

    async def assess(self, symbol: str, as_of_time: datetime) -> List[MarketContextAssessment]: ...


class RankingService(Protocol):
    """Deterministic given identical candidate/evidence/correlation inputs — no randomness,
    no LLM. ranking_status=RESEARCH_ONLY is required whenever expected edge or a calibrated
    probability isn't available (Section 9.3)."""

    def rank(
        self, candidates: List[TradeCandidate], evidence_by_candidate: Dict[UUID, EvidenceRecord],
        correlation_snapshots: List[CorrelationSnapshot],
    ) -> List[RankingResult]: ...


class CorrelationService(Protocol):
    """Never returns 0.0 for a missing/insufficient-sample pair — correlation=None with a
    reason_code is required (Section 9.4: "no missing-correlation-as-zero behavior")."""

    MINIMUM_SAMPLE_COUNT: int = 30

    def snapshot(
        self, symbol_a: str, symbol_b: str, timeframe: Timeframe, as_of_time: datetime,
    ) -> CorrelationSnapshot: ...


class StrategyPortfolioService(Protocol):
    def eligible_sleeves(self, symbol: str, timeframe: Timeframe, regime: Any) -> List[Any]: ...


# --- Governance (Phase 5/6) ---


class EvidenceService(Protocol):
    """Exact-match only lookup (packages.evidence.store.EvidenceStore) — never a fallback
    across symbol/timeframe/strategy/config/model. Deterministic; no external dependency."""

    def lookup(self, key: EvidenceKey, as_of: Optional[datetime] = None) -> EvidenceLookupOutcome: ...


class PortfolioRiskService(Protocol):
    """Every decision returns exactly one of APPROVE/REDUCE/REJECT/HALT with full reasoning.
    Missing portfolio state (PortfolioSnapshot.available=False) must yield a conservative
    (REJECT or HALT) decision, never an implicit APPROVE. Deterministic; no external
    dependency — LLM output must never reach this service as an override input."""

    def evaluate(
        self, candidate: TradeCandidate, requested_risk_pct: Decimal, portfolio: PortfolioSnapshot,
    ) -> PortfolioRiskDecision: ...


# --- Runtime (Phase 7) ---


class RecommendationService(Protocol):
    """The end-to-end orchestrator (Phase 7). Must return a typed RecommendationResult even
    when every intelligence layer is degraded/disabled/empty — never raises for an expected
    "no evidence" / "no model" / "stale data" condition, only for genuine infrastructure
    failure (and even then, via a typed PortError)."""

    DEFAULT_TIMEOUT_SECONDS: float = 30.0

    async def scan(self, request: RecommendationRequest) -> RecommendationResult: ...

    async def analyze(self, request: RecommendationRequest, symbol: str) -> RecommendationResult: ...


# --- Shadow / Monitoring / Drift / Retraining (Phase 10-12) ---


class ShadowService(Protocol):
    def record_proposal(self, snapshot: ShadowProposal) -> ShadowProposal: ...

    def schedule_evaluation(self, shadow_id: UUID, due_at: datetime) -> ShadowOutcome: ...

    async def evaluate_due(self, as_of_time: datetime) -> List[ShadowOutcome]: ...


class MonitoringService(Protocol):
    def record_metric(self, name: str, value: Decimal, tags: Optional[Dict[str, str]] = None) -> None: ...

    def current_readiness(self) -> ReadinessStatus: ...


class DriftService(Protocol):
    def assess(
        self, subject: str, metric_name: str, baseline: Optional[Decimal], current: Optional[Decimal],
    ) -> DriftAssessment: ...


class RetrainingService(Protocol):
    """A retrained model always enters RESEARCH_ONLY (Section 17) — this port has no method
    that can promote a model to APPROVED; promotion is a separate, human-gated registry
    operation (packages.registries.model_registry), never automatic."""

    async def run_training_job(self, dataset_checksum: str, feature_version: str, label_version: str) -> str: ...
