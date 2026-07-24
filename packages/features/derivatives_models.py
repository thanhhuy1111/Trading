"""Models for the derivatives feature pipeline (Multi-Agent Trading Advisor plan, Phase 2).

Mirrors `packages.features.models` but with sample-based lineage instead of candle-based
lineage -- a `DerivativesSnapshot` history is a sequence of point-in-time polls, not a
regular-interval candle series, so "how many candles were used, oldest/newest candle
timestamp" doesn't fit; "how many samples were used, oldest/newest sample timestamp" does.
Reuses `FeatureValue`, `FeatureQualityStatus`, `FeatureQualityIssue` from
`packages.features.models` as-is -- those are already generic, not candle-specific.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.features.models import FeatureQualityIssue, FeatureQualityStatus


class DerivativesFeatureLineage(BaseModel):
    source_exchange: str
    source_symbol: str
    sample_count: int
    oldest_sample_timestamp: Optional[datetime]
    newest_sample_timestamp: Optional[datetime]
    calculator_versions: Dict[str, str]


class DerivativesFeatureComputationRequest(BaseModel):
    exchange: str
    symbol: str
    feature_set: str
    as_of_time: datetime


class DerivativesFeatureContext(BaseModel):
    exchange: str
    symbol: str
    as_of_time: datetime


class DerivativesFeatureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID = Field(default_factory=uuid4)
    exchange: str
    symbol: str
    feature_set: str
    feature_set_version: str
    as_of_time: datetime
    computed_at: datetime
    values: Dict[str, Optional[Decimal | int | bool]]
    quality_status: FeatureQualityStatus
    quality_issues: List[FeatureQualityIssue] = Field(default_factory=list)
    lineage: DerivativesFeatureLineage
    schema_version: int = 1

    @model_validator(mode="after")
    def validate_temporal_invariants(self) -> "DerivativesFeatureSnapshot":
        newest = self.lineage.newest_sample_timestamp
        if newest is not None and newest > self.as_of_time:
            raise ValueError(
                f"Lookahead Leakage Violation: newest_sample_timestamp ({newest}) > as_of_time ({self.as_of_time})"
            )
        return self
