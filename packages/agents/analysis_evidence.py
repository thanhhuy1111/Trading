"""Immutable, analysis-scoped evidence records for specialist agents."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.retraining.xgboost_contracts import PRICE_FEATURE_NAMES

TECHNICAL_EVIDENCE_NAMES = frozenset(PRICE_FEATURE_NAMES)
DERIVATIVES_EVIDENCE_NAMES = frozenset(
    {
        "funding_rate",
        "open_interest",
        "long_short_account_ratio",
        "taker_buy_sell_ratio",
        "futures_basis_bps",
        "funding_rate_zscore_20",
        "open_interest_roc_12",
        "futures_basis_momentum_6",
    }
)
QUANTITATIVE_EVIDENCE_NAMES = frozenset(
    {
        "bearish_probability",
        "neutral_probability",
        "bullish_probability",
        "confidence",
    }
)


class AnalysisEvidenceCategory(str, Enum):
    TECHNICAL = "TECHNICAL"
    DERIVATIVES = "DERIVATIVES"
    QUANTITATIVE = "QUANTITATIVE"


_ALLOWED_NAMES = {
    AnalysisEvidenceCategory.TECHNICAL: TECHNICAL_EVIDENCE_NAMES,
    AnalysisEvidenceCategory.DERIVATIVES: DERIVATIVES_EVIDENCE_NAMES,
    AnalysisEvidenceCategory.QUANTITATIVE: QUANTITATIVE_EVIDENCE_NAMES,
}
_EXPECTED_UNITS = {
    AnalysisEvidenceCategory.TECHNICAL: {
        "return_1p": "ratio",
        "return_3p": "ratio",
        "return_5p": "ratio",
        "high_low_range": "ratio",
        "ema_20_slope": "ratio",
        "adx_14": "index",
        "rsi_14": "index",
        "atr_14": "quote_currency",
        "volatility_20": "ratio",
        "relative_volume_20": "ratio",
        "zscore_20": "index",
        "bollinger_pos_20": "ratio",
        "donchian_breakout_20": "signal",
    },
    AnalysisEvidenceCategory.DERIVATIVES: {
        "funding_rate": "ratio",
        "open_interest": "base_asset",
        "long_short_account_ratio": "ratio",
        "taker_buy_sell_ratio": "ratio",
        "futures_basis_bps": "basis_points",
        "funding_rate_zscore_20": "index",
        "open_interest_roc_12": "ratio",
        "futures_basis_momentum_6": "basis_points",
    },
    AnalysisEvidenceCategory.QUANTITATIVE: {
        "bearish_probability": "probability",
        "neutral_probability": "probability",
        "bullish_probability": "probability",
        "confidence": "probability",
    },
}


class AnalysisEvidenceStatus(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"


class AnalysisEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["analysis_evidence_v1"] = "analysis_evidence_v1"
    evidence_id: str = Field(min_length=1)
    analysis_id: str = Field(min_length=1)
    category: AnalysisEvidenceCategory
    feature_set: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    numeric_value: Decimal
    unit: str = Field(min_length=1)
    observed_at: datetime
    available_at: datetime
    source_id: str = Field(min_length=1)
    status: AnalysisEvidenceStatus = AnalysisEvidenceStatus.VALID

    @field_validator(
        "evidence_id",
        "analysis_id",
        "feature_set",
        "feature_set_version",
        "name",
        "unit",
        "source_id",
    )
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if value != value.strip() or not value.strip():
            raise ValueError("evidence strings must be nonblank and trimmed")
        return value

    @model_validator(mode="after")
    def validate_record(self) -> "AnalysisEvidenceRecord":
        if self.observed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        if self.observed_at > self.available_at:
            raise ValueError("evidence cannot be available before observation")
        if self.name not in _ALLOWED_NAMES[self.category]:
            raise ValueError("evidence name is not allowed for category schema")
        expected_feature_set = {
            AnalysisEvidenceCategory.TECHNICAL: ("standard_v1", "1.0.0"),
            AnalysisEvidenceCategory.DERIVATIVES: ("derivatives_v1", "1.0.0"),
            AnalysisEvidenceCategory.QUANTITATIVE: ("xgboost_direction", "1.0.0"),
        }[self.category]
        if (
            self.feature_set,
            self.feature_set_version,
        ) != expected_feature_set:
            raise ValueError("evidence feature schema/version mismatch")
        if self.unit != _EXPECTED_UNITS[self.category][self.name]:
            raise ValueError("evidence metric unit mismatch")
        if (
            self.name in {"rsi_14", "adx_14"}
            and not Decimal("0") <= self.numeric_value <= Decimal("100")
        ):
            raise ValueError("bounded index evidence is outside its domain")
        if self.name in {
            "high_low_range",
            "atr_14",
            "volatility_20",
            "relative_volume_20",
            "open_interest",
            "long_short_account_ratio",
            "taker_buy_sell_ratio",
        } and self.numeric_value < 0:
            raise ValueError("nonnegative evidence is outside its domain")
        if (
            self.category == AnalysisEvidenceCategory.QUANTITATIVE
            and (
                self.unit != "probability"
                or not self.source_id.startswith("approved_runtime:")
                or self.numeric_value < 0
                or self.numeric_value > 1
            )
        ):
            raise ValueError("quantitative evidence must bind to approved runtime")
        return self


class AnalysisEvidenceRegistry:
    def __init__(self) -> None:
        self._records: Dict[str, AnalysisEvidenceRecord] = {}

    def register(self, record: AnalysisEvidenceRecord) -> AnalysisEvidenceRecord:
        if record.evidence_id in self._records:
            raise ValueError("ANALYSIS_EVIDENCE_ID_EXISTS")
        self._records[record.evidence_id] = record
        return record

    def resolve(
        self,
        *,
        analysis_id: str,
        evidence_ids: Sequence[str],
        category: AnalysisEvidenceCategory,
        as_of_time: datetime,
    ) -> tuple[Optional[Tuple[AnalysisEvidenceRecord, ...]], Optional[str]]:
        if as_of_time.tzinfo is None:
            return None, "ANALYSIS_AS_OF_INVALID"
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            return None, "EVIDENCE_REFERENCE_SET_INVALID"
        records: list[AnalysisEvidenceRecord] = []
        for evidence_id in evidence_ids:
            record = self._records.get(evidence_id)
            if record is None:
                return None, "EVIDENCE_NOT_FOUND"
            if record.analysis_id != analysis_id:
                return None, "EVIDENCE_ANALYSIS_MISMATCH"
            if record.category != category:
                return None, "EVIDENCE_CATEGORY_MISMATCH"
            if record.status == AnalysisEvidenceStatus.STALE:
                return None, "EVIDENCE_STALE"
            if record.status != AnalysisEvidenceStatus.VALID:
                return None, "EVIDENCE_INVALID"
            if (
                record.observed_at > as_of_time
                or record.available_at > as_of_time
            ):
                return None, "EVIDENCE_LOOKAHEAD_VIOLATION"
            records.append(record)
        return tuple(records), None

    def get(self, evidence_id: str) -> Optional[AnalysisEvidenceRecord]:
        return self._records.get(evidence_id)
