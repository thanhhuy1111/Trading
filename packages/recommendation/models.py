"""Typed domain models for the AI Trading Advisor recommendation layer.

These models are the single source of truth for every fact that may appear in a chat
answer. The Gemini chat agent (packages/chat_agent) only ever sees these types, serialized
as tool output -- it never sees raw prices, features, or internal governance objects, and
it cannot construct or mutate any of them itself.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    NO_TRADE = "NO_TRADE"


class RecommendationStatus(str, Enum):
    PROPOSALS_AVAILABLE = "PROPOSALS_AVAILABLE"
    NO_TRADE = "NO_TRADE"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
    STRATEGY_NOT_APPROVED = "STRATEGY_NOT_APPROVED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class EvidenceStatus(str, Enum):
    APPROVED = "APPROVED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    INSUFFICIENT = "INSUFFICIENT"
    REJECTED = "REJECTED"
    STALE = "STALE"


class MarketStatus(str, Enum):
    NORMAL = "NORMAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


# --------------------------------------------------------------------------------------
# Market overview (get_market_overview tool)
# --------------------------------------------------------------------------------------


class TimeframeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: str
    market_regime: str
    volatility_bucket: str
    last_close: Decimal
    close_time: datetime
    freshness_seconds: float


class SymbolMarketOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    market_status: MarketStatus
    last_price: Optional[Decimal] = None
    data_timestamp: Optional[datetime] = None
    freshness_seconds: Optional[float] = None
    liquidity_status: str = "UNKNOWN"
    timeframes: List[TimeframeSnapshot] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)


class MarketOverview(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    overall_market_status: MarketStatus
    symbols: List[SymbolMarketOverview]


# --------------------------------------------------------------------------------------
# Candidate -> proposal pipeline
# --------------------------------------------------------------------------------------


class TradeCandidate(BaseModel):
    """A single symbol/timeframe opportunity produced by the real decision pipeline.

    Every field is sourced from DecisionService output (features -> agents -> critic ->
    consensus -> allocator). Nothing here is invented by this package or by the LLM.
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    side: str
    timeframe: str
    horizon_minutes: int
    strategy_names: List[str]
    strategy_version: str
    reference_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    raw_confidence: Decimal
    expected_return_bps: Decimal
    net_edge_bps: Decimal
    market_regime: str
    liquidity_score: Decimal
    spread_bps: Decimal
    reason_codes: List[str]
    feature_snapshot_id: str
    feature_set_version: str
    data_timestamp: datetime
    freshness_seconds: float
    config_hash: str
    decision_lineage: "DecisionLineage"


class DecisionLineage(BaseModel):
    """Full audit trail from raw candles to this candidate/proposal."""

    model_config = ConfigDict(frozen=True)

    feature_snapshot_id: str
    market_regime: str
    signal_ids: List[str]
    critic_decision_ids: List[str]
    consensus_id: str
    allocation_id: str
    trade_intent_id: Optional[str] = None
    prediction_id: Optional[str] = None
    evidence_id: Optional[str] = None
    config_hash: str


class TradeProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    side: str
    status: ProposalStatus
    timeframe: str
    horizon_minutes: int

    entry_from: Decimal
    entry_to: Decimal
    stop_loss: Decimal
    take_profit_levels: List[Decimal]

    probability_profit: Decimal
    expected_gross_return_bps: Decimal
    estimated_cost_bps: Decimal
    expected_net_return_bps: Decimal
    expected_downside_bps: Decimal
    risk_reward_ratio: Decimal
    opportunity_score: Decimal

    market_regime: str
    data_timestamp: datetime
    freshness_seconds: float
    generated_at: datetime
    expires_at: datetime

    strategy_name: str
    strategy_version: str
    model_version: str
    feature_version: str
    config_hash: str

    evidence_id: Optional[str] = None
    explanation_facts: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    decision_lineage: DecisionLineage

    is_simulated: bool = False
    simulation_label: Optional[str] = None


class RecommendationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    status: RecommendationStatus
    generated_at: datetime
    market_status: MarketStatus
    proposals: List[TradeProposal] = Field(default_factory=list)
    rejected_candidates: int = 0
    no_trade_reasons: List[str] = Field(default_factory=list)
    symbols_evaluated: List[str] = Field(default_factory=list)
    no_trade_symbols: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    proposal_id: str
    reason_codes: List[str] = Field(default_factory=list)
    checked_at: datetime


# --------------------------------------------------------------------------------------
# Strategy evidence (out-of-sample proof; see evidence_service.py)
# --------------------------------------------------------------------------------------


class StrategyEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_name: str
    strategy_version: str
    model_version: str
    feature_version: str
    dataset_checksum: Optional[str] = None
    config_hash: str
    code_commit: Optional[str] = None

    train_period: Optional[str] = None
    validation_period: Optional[str] = None
    test_period: Optional[str] = None
    walk_forward_windows: int = 0

    out_of_sample_trades: int = 0
    net_pnl_pct: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None
    sharpe: Optional[Decimal] = None
    sortino: Optional[Decimal] = None
    calmar: Optional[Decimal] = None
    maximum_drawdown_pct: Optional[Decimal] = None
    expectancy_bps: Optional[Decimal] = None
    turnover: Optional[Decimal] = None
    estimated_fees_bps: Optional[Decimal] = None
    estimated_slippage_bps: Optional[Decimal] = None
    calibration_metrics: Optional[str] = None

    status: EvidenceStatus
    reason_codes: List[str] = Field(default_factory=list)
    created_at: datetime


TradeCandidate.model_rebuild()
