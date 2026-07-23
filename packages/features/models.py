from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.market_data.models import Timeframe


class FeatureQualityStatus(str, Enum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    WARMING_UP = "WARMING_UP"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class FeatureQualityIssue(BaseModel):
    feature_name: str
    issue_type: str
    description: str
    severity: str  # ERROR, WARNING, INFO
    timestamp: datetime


class FeatureLineage(BaseModel):
    source_exchange: str
    source_symbol: str
    source_timeframe: str
    candle_count_used: int
    oldest_candle_timestamp: datetime
    newest_candle_timestamp: datetime
    calculator_versions: Dict[str, str]


class FeatureDefinition(BaseModel):
    name: str
    version: str
    category: str  # price_return, trend, momentum, volatility, volume, mean_reversion, breakout, market_quality
    description: str
    required_lookback: int
    supported_timeframes: List[Timeframe]
    output_type: str  # Decimal, int, bool
    missing_policy: str  # REJECT, FORWARD_FILL, DEFAULT
    warmup_policy: str  # STRICT, PARTIAL
    owner: str = "quant_team"
    is_deprecated: bool = False


class FeatureValue(BaseModel):
    name: str
    version: str
    value: Optional[Decimal | int | bool]
    is_valid: bool
    error_message: Optional[str] = None


class FeatureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID = Field(default_factory=uuid4)
    exchange: str
    symbol: str
    timeframe: Timeframe
    feature_set: str
    feature_set_version: str
    event_time: datetime
    as_of_time: datetime
    computed_at: datetime
    lookback_start: datetime
    lookback_end: datetime
    values: Dict[str, Optional[Decimal | int | bool]]
    quality_status: FeatureQualityStatus
    quality_issues: List[FeatureQualityIssue] = Field(default_factory=list)
    source_data_version: str
    lineage: FeatureLineage
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_temporal_invariants(self) -> "FeatureSnapshot":
        if self.lookback_end > self.as_of_time:
            msg = f"Lookahead Leakage Violation: lookback_end ({self.lookback_end}) > as_of_time ({self.as_of_time})"
            raise ValueError(msg)
        if self.event_time > self.as_of_time:
            msg = f"Lookahead Leakage Violation: event_time ({self.event_time}) > as_of_time ({self.as_of_time})"
            raise ValueError(msg)
        return self


class FeatureSetDefinition(BaseModel):
    name: str
    version: str
    features: List[str]  # Feature names
    checksum: str
    description: str


class FeatureContext(BaseModel):
    exchange: str
    symbol: str
    timeframe: Timeframe
    as_of_time: datetime
    data_quality_status: str


class FeatureComputationRequest(BaseModel):
    exchange: str
    symbol: str
    timeframe: Timeframe
    feature_set: str
    as_of_time: datetime
    mode: str = "incremental"  # incremental, batch, replay
