"""Typed contracts for the Prediction Service.

CRITICAL INVARIANT: nothing in this module or its implementations may fabricate a
probability. When no trained, calibrated model artifact is registered for a given
symbol/timeframe/horizon, `PredictionService.predict()` returns a `ModelPrediction`
with `calibration_status=UNAVAILABLE` and `probability_profit=None`. Callers (the
recommendation pipeline) MUST treat that as "cannot evaluate" (INSUFFICIENT_EVIDENCE),
never as "no edge" (NO_TRADE) and never substitute a heuristic agent confidence score
in its place -- confidence is a rule-based proxy, not a calibrated probability.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class CalibrationStatus(str, Enum):
    CALIBRATED = "CALIBRATED"
    UNCALIBRATED = "UNCALIBRATED"
    UNAVAILABLE = "UNAVAILABLE"


class ModelPrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    prediction_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    timeframe: str
    horizon_minutes: int

    probability_up: Optional[Decimal] = None
    probability_down: Optional[Decimal] = None
    probability_flat: Optional[Decimal] = None
    probability_profit: Optional[Decimal] = None
    expected_return_bps: Optional[Decimal] = None
    expected_volatility_bps: Optional[Decimal] = None

    calibration_status: CalibrationStatus
    calibration_score: Optional[Decimal] = None
    model_version: str
    feature_snapshot_id: str
    generated_at: datetime

    reason_codes: list[str] = Field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.calibration_status == CalibrationStatus.CALIBRATED and self.probability_profit is not None
