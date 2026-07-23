from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.features.models import FeatureSnapshot
from packages.market_data.models import Timeframe


class MarketRegime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    TRANSITION = "TRANSITION"
    LIQUIDITY_RISK = "LIQUIDITY_RISK"
    UNKNOWN = "UNKNOWN"


class SignalAction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    NO_SIGNAL = "NO_SIGNAL"


class StrategyType(str, Enum):
    TREND_FOLLOWING = "TREND_FOLLOWING"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    REGIME_CLASSIFIER = "REGIME_CLASSIFIER"


class AgentSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    agent_name: str
    agent_version: str
    strategy_type: StrategyType
    exchange: str
    symbol: str
    timeframe: Timeframe
    action: SignalAction
    expected_return_bps: Optional[Decimal] = None
    confidence: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    horizon_minutes: int
    reference_price: Decimal
    invalidation_price: Optional[Decimal] = None
    suggested_stop_price: Optional[Decimal] = None
    suggested_take_profit_price: Optional[Decimal] = None
    market_regime: MarketRegime
    feature_snapshot_id: UUID
    feature_set_version: str
    feature_as_of_time: datetime
    generated_at: datetime
    expires_at: datetime
    reason_codes: List[str] = Field(default_factory=list)
    explanation: List[str] = Field(default_factory=list)
    quality_flags: List[str] = Field(default_factory=list)
    confidence_type: str = "HEURISTIC_SCORE"
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_safety_restrictions(self) -> "AgentSignal":
        # Ensure no execution parameters exist
        if hasattr(self, "quantity") or hasattr(self, "notional") or hasattr(self, "leverage"):
            msg = "Safety Violation: AgentSignal must NOT contain trading execution parameters"
            raise ValueError(msg)
        return self


class AgentEvaluationContext(BaseModel):
    exchange: str
    symbol: str
    timeframe: Timeframe
    as_of_time: datetime
    feature_snapshot: FeatureSnapshot
    market_regime: MarketRegime
    data_quality_status: str
    agent_config: Dict[str, Any] = Field(default_factory=dict)
