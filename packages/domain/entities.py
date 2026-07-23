"""Core domain entities for the architecture-complete Trading Advisor (Phase 1).

Where a stable entity already exists from Checkpoint 1/2, this module re-exports it rather
than duplicating/conflicting with it (Section 4, rule 20: "preserve all prior research
artifacts and existing behavior unless explicitly migrated"):

    MarketDataset        -> packages.backtest.models.HistoricalDatasetDefinition
    DatasetQualityReport -> packages.market_data.historical_quality.DatasetQualityReport
    FeatureSnapshot      -> packages.features.models.FeatureSnapshot
    RegimeAssessment     -> packages.agents.regime.RegimeResult
    StrategyRoute        -> packages.governance.strategy_router.RoutingDecision
    TradeCandidate       -> packages.candidates.models.TradeCandidate
    EvidenceRecord       -> packages.evidence.models.EvidenceRecord

Every entity defined fresh here (the ones with no Checkpoint 1/2 equivalent) carries the
minimum fields the task requires: version, created_at, source identifiers, checksum where
appropriate, reason_codes, status.
"""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# Re-exports (see module docstring). Importers should generally prefer importing from here
# (packages.domain.entities) for anything cross-cutting so a single module lists "the domain
# model", even though the implementation lives in its original, still-canonical location.
from packages.agents.regime import RegimeResult as RegimeAssessment  # noqa: F401
from packages.backtest.models import HistoricalDatasetDefinition as MarketDataset  # noqa: F401
from packages.candidates.models import TradeCandidate  # noqa: F401
from packages.domain.enums import (
    ApplicationResultState,
    ArchitectureReadiness,
    DriftSeverity,
    EvidenceReadiness,
    LiveReadiness,
    MarketContextStatus,
    MetaLabelDecision,
    ModelReadiness,
    ModelType,
    PortfolioRiskDecisionType,
    RankingStatus,
    ShadowOutcomeStatus,
    ShadowProposalKind,
    StrategyReadiness,
)
from packages.evidence.models import EvidenceRecord  # noqa: F401
from packages.features.models import FeatureSnapshot  # noqa: F401
from packages.governance.strategy_router import RoutingDecision as StrategyRoute  # noqa: F401
from packages.market_data.historical_quality import DatasetQualityReport  # noqa: F401

__all__ = [
    # Re-exports (see module docstring) — listed explicitly so static type checkers treat
    # them as part of this module's public API, not as unused imports.
    "RegimeAssessment",
    "MarketDataset",
    "TradeCandidate",
    "EvidenceRecord",
    "FeatureSnapshot",
    "StrategyRoute",
    "DatasetQualityReport",
    # Entities defined in this module.
    "AgentAssessment",
    "CandidateOutcome",
    "ModelPrediction",
    "MarketContextAssessment",
    "RankingResult",
    "CorrelationSnapshot",
    "PortfolioRiskDecision",
    "TradeProposal",
    "ShadowProposal",
    "ShadowOutcome",
    "DriftAssessment",
    "ReadinessStatus",
    "stable_checksum",
]


def _new_id() -> UUID:
    return uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentAssessment(BaseModel):
    """One agent's contribution to a single decision point — the piece of the pipeline
    between a raw AgentSignal/CriticDecision pair and the aggregated TradeCandidate. Exists
    as its own entity so agent-level attribution (already used in BTC_ETH_FAILURE_ANALYSIS.md)
    has a stable, versioned shape independent of the candidate it ends up contributing to."""

    assessment_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    agent_id: str
    agent_version: str
    symbol: str
    timeframe: str
    as_of_time: datetime
    signal_id: UUID
    action: str
    confidence: Decimal
    adjusted_confidence: Decimal
    approved_for_aggregation: bool
    reason_codes: List[str] = Field(default_factory=list)
    status: str = "EVALUATED"


class CandidateOutcome(BaseModel):
    """The realized-outcome half of a TradeCandidate's lifecycle, split out as its own entity
    so shadow evaluation (Phase 10) and meta-label training (Phase 3/Checkpoint 3) can both
    reference "the outcome of candidate X" without re-deriving it from TradeCandidate's
    optional exit_* fields each time."""

    outcome_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    candidate_id: UUID
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[Decimal] = None
    gross_return_bps: Optional[Decimal] = None
    total_cost_bps: Optional[Decimal] = None
    net_return_bps: Optional[Decimal] = None
    exit_reason: Optional[str] = None
    meta_label: Optional[str] = None  # "ACCEPT" | "REJECT", None while unresolved
    reason_codes: List[str] = Field(default_factory=list)
    status: str = "PENDING"  # PENDING | RESOLVED | CENSORED (dataset ended before resolution)


class ModelPrediction(BaseModel):
    """Output of a MetaLabelService (Phase 4/9) for one candidate. `probability=None` is the
    honest, required value for the baseline PassThroughMetaLabelService — never fabricated."""

    prediction_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    candidate_id: UUID
    model_type: ModelType
    model_version: str
    feature_version: str
    label_version: str
    probability: Optional[Decimal] = None  # calibrated probability, or None if unavailable
    decision: MetaLabelDecision
    reason_codes: List[str] = Field(default_factory=list)
    status: str = "BASELINE_ONLY"


class MarketContextAssessment(BaseModel):
    """Output of one LLM/context agent (News/Macro/Sentiment/RiskCritic — Phase 9). The
    disabled/no-op adapters (Phase 4.2) return status=NOT_AVAILABLE with every numeric field
    null — never a fabricated view."""

    assessment_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    agent_name: str
    agent_version: str
    created_at: datetime = Field(default_factory=_now)
    analysis_timestamp: datetime = Field(default_factory=_now)
    decision_timestamp: Optional[datetime] = None
    source_ids: List[str] = Field(default_factory=list)
    source_timestamps: List[datetime] = Field(default_factory=list)
    view: Optional[str] = None
    confidence: Optional[Decimal] = None
    risk_level: Optional[str] = None
    risk_adjustment: Decimal = Decimal("0")
    status: MarketContextStatus = MarketContextStatus.NOT_AVAILABLE
    reason_codes: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class RankingResult(BaseModel):
    ranking_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    ranking_version: str
    candidate_id: UUID
    rank: Optional[int] = None
    ranking_score: Optional[Decimal] = None
    ranking_status: RankingStatus
    expected_net_edge_bps: Optional[Decimal] = None
    evidence_weight: Decimal = Decimal("0")
    liquidity_weight: Decimal = Decimal("0")
    data_freshness_weight: Decimal = Decimal("0")
    cost_penalty: Decimal = Decimal("0")
    correlation_penalty: Decimal = Decimal("0")
    risk_penalty: Decimal = Decimal("0")
    reason_codes: List[str] = Field(default_factory=list)


class CorrelationSnapshot(BaseModel):
    snapshot_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    window_config_version: str
    symbol_a: str
    symbol_b: str
    timeframe: str
    window_bars: int
    sample_count: int
    correlation: Optional[Decimal] = None  # None (never 0.0) when unavailable/insufficient
    computed_at: datetime = Field(default_factory=_now)
    is_stale: bool = False
    reason_codes: List[str] = Field(default_factory=list)
    status: str = "OK"  # OK | INSUFFICIENT_SAMPLE | STALE | UNAVAILABLE


class PortfolioRiskDecision(BaseModel):
    decision_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    policy_version: str
    candidate_id: Optional[UUID] = None
    decision: PortfolioRiskDecisionType
    requested_risk_pct: Decimal
    approved_risk_pct: Decimal
    portfolio_snapshot_id: Optional[UUID] = None
    reason_codes: List[str] = Field(default_factory=list)


class TradeProposal(BaseModel):
    proposal_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    candidate_id: UUID
    symbol: str
    timeframe: str
    direction: str
    entry_reference: Decimal
    entry_zone_low: Optional[Decimal] = None
    entry_zone_high: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    risk_reward_ratio: Optional[Decimal] = None
    estimated_fee_bps: Decimal
    estimated_spread_bps: Decimal
    estimated_slippage_bps: Decimal
    expected_net_return_bps: Optional[Decimal] = None
    calibrated_probability: Optional[Decimal] = None
    strategy_version: str
    model_version: str
    evidence_status: str
    ranking_score: Optional[Decimal] = None
    approved_risk_pct: Optional[Decimal] = None
    proposal_expiry: datetime
    reason_codes: List[str] = Field(default_factory=list)
    application_result_state: ApplicationResultState


class ShadowProposal(BaseModel):
    """Immutable snapshot (Phase 10). Every field is captured at creation time and never
    mutated afterward — outcome evaluation appends a separate ShadowOutcome record instead of
    editing this one, so the original decision context is always reconstructable exactly."""

    model_config = {"frozen": True}

    shadow_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    kind: ShadowProposalKind
    proposal_id: UUID
    candidate_snapshot: Dict[str, Any]
    feature_snapshot: Dict[str, Any]
    regime_snapshot: Dict[str, Any]
    agent_assessments_snapshot: List[Dict[str, Any]]
    meta_label_snapshot: Dict[str, Any]
    market_context_snapshot: List[Dict[str, Any]]
    evidence_snapshot: Dict[str, Any]
    ranking_snapshot: Dict[str, Any]
    correlation_snapshot: Optional[Dict[str, Any]] = None
    portfolio_risk_snapshot: Dict[str, Any]
    market_data_timestamp: datetime
    code_commit: str
    configuration_versions: Dict[str, str]
    checksum: str = ""

    def compute_checksum(self) -> str:
        payload = self.model_dump_json(exclude={"checksum", "shadow_id", "created_at"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ShadowOutcome(BaseModel):
    outcome_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    shadow_id: UUID
    status: ShadowOutcomeStatus = ShadowOutcomeStatus.PENDING
    evaluation_due_at: datetime
    evaluated_at: Optional[datetime] = None
    actual_entry_reference: Optional[Decimal] = None
    actual_exit_reference: Optional[Decimal] = None
    gross_return_bps: Optional[Decimal] = None
    total_cost_bps: Optional[Decimal] = None
    net_return_bps: Optional[Decimal] = None
    barrier_hit: Optional[str] = None  # UPPER | LOWER | None
    reason_codes: List[str] = Field(default_factory=list)


class DriftAssessment(BaseModel):
    assessment_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    subject: str  # e.g. "feature:rsi_14", "model:lr_v1", "strategy:baseline/BTCUSDT/1h"
    metric_name: str
    baseline_value: Optional[Decimal] = None
    current_value: Optional[Decimal] = None
    severity: DriftSeverity
    reason_codes: List[str] = Field(default_factory=list)
    recommended_action: Optional[str] = None


class ReadinessStatus(BaseModel):
    """The one entity that must never be conflated across its six axes (Section 3)."""

    readiness_id: UUID = Field(default_factory=_new_id)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=_now)
    architecture_readiness: ArchitectureReadiness
    strategy_readiness: StrategyReadiness
    model_readiness: ModelReadiness
    evidence_readiness: EvidenceReadiness
    shadow_readiness: str  # ShadowReadiness value, kept as str to avoid an import-order issue
    live_readiness: LiveReadiness = LiveReadiness.DISABLED
    reason_codes: List[str] = Field(default_factory=list)
    code_commit: Optional[str] = None


def stable_checksum(payload: Dict[str, Any]) -> str:
    """Shared checksum helper: deterministic across runs given the same content (sorted keys,
    stable JSON serialization) — used anywhere a "checksum where appropriate" field needs one
    without each entity reimplementing it slightly differently."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
