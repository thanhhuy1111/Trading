"""TradeCandidate: the explicit lineage entity between a governance decision and a realized
trade outcome (or non-outcome, if rejected/never filled).

Every field is derived strictly from real, already-computed objects produced by the existing
production pipeline (DecisionService, DeterministicRiskGovernor, ExitProtector, PortfolioLedger)
at the time the decision was made — nothing here is inferred, estimated, or fabricated after the
fact. Lineage:

    Market candle -> FeatureSnapshot -> AgentSignal(s) -> Consensus/Allocation -> TradeIntent
    -> [TradeCandidate created, status=PROPOSED]
    -> Risk Governor evaluation -> [RISK_REJECTED] or [APPROVED]
    -> Entry fill (if approved and next-bar liquidity exists) -> [FILLED]
    -> Exit fill (stop/take-profit/trailing, or still open at dataset end) -> [CLOSED] or stays FILLED
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CandidateStatus(str, Enum):
    PROPOSED = "PROPOSED"            # DecisionService produced a TradeIntent
    RISK_REJECTED = "RISK_REJECTED"  # Deterministic Risk Governor rejected the intent
    APPROVED = "APPROVED"            # Risk governor approved, but no fill occurred (e.g. no next bar)
    FILLED = "FILLED"                # Entry fill executed; position open
    CLOSED = "CLOSED"                # Exit fill executed; outcome fields populated


class TradeCandidate(BaseModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    symbol: str
    timeframe: str
    decision_timestamp: datetime
    direction: str  # "LONG" — the only executable direction in this spot-only MVP

    # Agent attribution. `agent_source` is the accepted, direction-agreeing signal with the
    # highest critic-adjusted confidence (the dominant contributor to this candidate); ties
    # broken by agent_id for determinism. This is a stated attribution convention, not a
    # claim that the other agents had no influence — see supporting/opposing_agents for the
    # full picture.
    agent_source: str
    agent_confidence: Decimal
    supporting_agents: List[str] = Field(default_factory=list)
    opposing_agents: List[str] = Field(default_factory=list)
    consensus_score: Decimal
    critic_result: str
    allocator_result: str

    strategy_name: str
    strategy_version: str
    strategy_config_hash: str
    market_regime: str
    feature_snapshot: Dict[str, Optional[str]]  # feature name -> stringified value (JSON-safe)

    entry_reference: Decimal
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    risk_reward_ratio: Optional[Decimal] = None
    estimated_fee_bps: Decimal
    estimated_spread_bps: Decimal
    estimated_slippage_bps: Decimal

    status: CandidateStatus = CandidateStatus.PROPOSED
    risk_rejection_reasons: List[str] = Field(default_factory=list)
    actual_entry_price: Optional[Decimal] = None
    fold_number: Optional[int] = None

    # Populated only once the position is closed (status=CLOSED)
    exit_timestamp: Optional[datetime] = None
    exit_price: Optional[Decimal] = None
    gross_return_bps: Optional[Decimal] = None
    total_cost_bps: Optional[Decimal] = None
    net_return_bps: Optional[Decimal] = None
    exit_reason: Optional[str] = None
    label_end_timestamp: Optional[datetime] = None
    # Per Phase 8 target definition: ACCEPT iff net_return_bps > 0, else REJECT. None while open.
    meta_label: Optional[str] = None
