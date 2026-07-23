from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.agents.models import MarketRegime
from packages.market_data.models import Timeframe


class CriticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConsensusDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AllocationResult(str, Enum):
    TRADE_INTENT_CREATED = "TRADE_INTENT_CREATED"
    NO_TRADE = "NO_TRADE"
    REJECTED = "REJECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    CONFLICTED = "CONFLICTED"
    EXPIRED = "EXPIRED"


class IntentSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SPOT_SHORT_NOT_EXECUTABLE = "SPOT_SHORT_NOT_EXECUTABLE"


class SignalValidationResult(BaseModel):
    valid: bool
    signal_id: UUID
    rejection_codes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    validated_at: datetime
    validator_version: str = "1.0.0"


class CriticComponentResult(BaseModel):
    critic_name: str
    critic_version: str = "1.0.0"
    passed: bool
    severity: CriticSeverity
    confidence_penalty: Decimal = Field(default=Decimal("0.0"), ge=Decimal("0.0"), le=Decimal("1.0"))
    reason_codes: List[str] = Field(default_factory=list)
    explanation: List[str] = Field(default_factory=list)
    evaluated_at: datetime


class CriticDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: UUID = Field(default_factory=uuid4)
    signal_id: UUID
    agent_id: str
    approved_for_aggregation: bool
    original_confidence: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    adjusted_confidence: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    confidence_penalty: Decimal = Field(ge=Decimal("0.0"))
    estimated_cost_bps: Decimal
    risk_flags: List[str] = Field(default_factory=list)
    warning_codes: List[str] = Field(default_factory=list)
    rejection_codes: List[str] = Field(default_factory=list)
    review_components: List[CriticComponentResult] = Field(default_factory=list)
    reviewed_at: datetime
    valid_until: datetime
    critic_version: str = "1.0.0"
    policy_version: str = "1.0.0"
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_confidence_penalty(self) -> "CriticDecision":
        if self.adjusted_confidence > self.original_confidence:
            raise ValueError("Critic Safety Invariant Violation: adjusted_confidence cannot exceed original_confidence")
        return self


class ConsensusResult(BaseModel):
    consensus_id: UUID = Field(default_factory=uuid4)
    symbol: str
    timeframe_scope: List[Timeframe]
    direction: ConsensusDirection
    agreement_score: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    disagreement_score: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    participating_signals: List[UUID]
    accepted_signals: List[UUID]
    rejected_signals: List[UUID]
    weighted_confidence: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    weighted_expected_return_bps: Decimal
    reason_codes: List[str] = Field(default_factory=list)
    generated_at: datetime
    consensus_version: str = "1.0.0"


class AllocationDecision(BaseModel):
    allocation_id: UUID = Field(default_factory=uuid4)
    symbol: str
    result: AllocationResult
    consensus: ConsensusResult
    source_signal_ids: List[UUID]
    critic_decision_ids: List[UUID]
    created_trade_intent_id: Optional[UUID] = None
    reason_codes: List[str] = Field(default_factory=list)
    decision_fingerprint: str
    evaluated_at: datetime
    allocator_version: str = "1.0.0"
    policy_version: str = "1.0.0"


class TradeIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent_id: UUID = Field(default_factory=uuid4)
    symbol: str
    exchange: str
    side: IntentSide
    status: Literal["PENDING_RISK_REVIEW"] = "PENDING_RISK_REVIEW"
    strategy_ids: List[str]
    source_signal_ids: List[UUID]
    critic_decision_ids: List[UUID]
    consensus_id: UUID
    market_regime: MarketRegime
    expected_return_bps: Decimal
    weighted_confidence: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    estimated_fee_bps: Decimal
    estimated_spread_bps: Decimal
    estimated_slippage_bps: Decimal
    uncertainty_buffer_bps: Decimal
    net_edge_bps: Decimal
    reference_price: Decimal
    invalidation_price: Optional[Decimal] = None
    suggested_stop_price: Optional[Decimal] = None
    suggested_take_profit_price: Optional[Decimal] = None
    horizon_minutes: int
    maximum_entry_slippage_bps: Decimal = Decimal("10.0")
    feature_as_of_time: datetime
    generated_at: datetime
    expires_at: datetime
    reason_codes: List[str] = Field(default_factory=list)
    policy_version: str = "1.0.0"
    allocator_version: str = "1.0.0"
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_safety_restrictions(self) -> "TradeIntent":
        forbidden_fields = [
            "quantity", "notional", "approved_notional", "leverage",
            "margin_mode", "order_type", "client_order_id", "risk_amount", "risk_percentage"
        ]
        for f in forbidden_fields:
            if hasattr(self, f):
                raise ValueError(f"Safety Violation: TradeIntent must NOT contain execution/sizing parameter '{f}'")
        return self
