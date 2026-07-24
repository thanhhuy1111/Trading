"""Contracts for the Phase 4 point-in-time XGBoost dataset.

These contracts deliberately contain no trainer or runtime-serving behavior. They make the
dataset's temporal lineage, schema version, rejection state, and deterministic fingerprint
explicit before any model is allowed to consume it.
"""

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.common.immutable import FrozenMapping
from packages.features.models import FeatureQualityStatus
from packages.market_data.derivatives_models import DerivativesMetricLineage
from packages.market_data.models import Timeframe

DATASET_VERSION = "xgb_direction_dataset_v1"
LABEL_VERSION = "volatility_band_1bar_v1"
PRICE_FEATURE_NAMES: Tuple[str, ...] = (
    "return_1p",
    "return_3p",
    "return_5p",
    "high_low_range",
    "ema_20_slope",
    "adx_14",
    "rsi_14",
    "atr_14",
    "volatility_20",
    "relative_volume_20",
    "zscore_20",
    "bollinger_pos_20",
    "donchian_breakout_20",
)
DERIVATIVES_FEATURE_NAMES: Tuple[str, ...] = (
    "funding_rate_zscore_20",
    "open_interest_roc_12",
)
LABEL_THRESHOLD_CANDIDATES: Tuple[Decimal, ...] = (
    Decimal("0.25"),
    Decimal("0.50"),
    Decimal("0.75"),
    Decimal("1.00"),
)
PRICE_FEATURE_SET = "standard_v1"
PRICE_FEATURE_SET_VERSION = "1.0.0"
DERIVATIVES_FEATURE_SET = "derivatives_v1"
DERIVATIVES_FEATURE_SET_VERSION = "1.0.0"
DERIVATIVES_CADENCE_SECONDS = 300
DERIVATIVES_CADENCE_TOLERANCE_SECONDS = 60


class DatasetMode(str, Enum):
    PRICE_ONLY = "price_only"
    PRICE_PLUS_DERIVATIVES = "price_plus_derivatives"


class TargetClass(str, Enum):
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    BULLISH = "BULLISH"


class DatasetBuildStatus(str, Enum):
    VALID = "VALID"
    REJECTED = "REJECTED"


class PriceFeatureLineage(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_exchange: str
    source_symbol: str
    source_timeframe: str
    candle_count_used: int = Field(ge=1)
    oldest_candle_timestamp: datetime
    newest_candle_timestamp: datetime
    source_available_at: datetime
    calculator_versions: FrozenMapping[str, str]


class DerivativesFeatureLineage(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_exchange: str
    source_symbol: str
    sample_count: int = Field(ge=1)
    oldest_sample_timestamp: datetime
    newest_sample_timestamp: datetime
    cadence_seconds: int = Field(gt=0)
    cadence_tolerance_seconds: int = Field(ge=0)
    metric_lineage: FrozenMapping[str, Tuple[DerivativesMetricLineage, ...]]
    calculator_versions: FrozenMapping[str, str]


class DatasetFeatureLineage(BaseModel):
    model_config = ConfigDict(frozen=True)

    price: PriceFeatureLineage
    derivatives: Optional[DerivativesFeatureLineage] = None


class XGBoostDatasetSample(BaseModel):
    model_config = ConfigDict(frozen=True)

    sample_id: str
    exchange_symbol: str
    canonical_symbol: str
    spot_exchange: str
    derivatives_exchange: Optional[str] = None
    timeframe: Timeframe
    as_of_time: datetime
    target_time: datetime
    close_at_as_of: Decimal
    future_close: Decimal
    future_return: Decimal
    rolling_volatility: Decimal = Field(ge=Decimal("0"))
    label_threshold_k: Decimal = Field(gt=Decimal("0"))
    label_threshold: Decimal = Field(ge=Decimal("0"))
    target_class: TargetClass
    dataset_mode: DatasetMode
    feature_names: Tuple[str, ...]
    feature_values: FrozenMapping[str, Decimal]
    feature_status: FeatureQualityStatus
    feature_lineage: DatasetFeatureLineage
    feature_available_at: datetime
    ingestion_audit: FrozenMapping[str, datetime] = Field(
        default_factory=lambda: FrozenMapping({})
    )
    reason_codes: Tuple[str, ...] = ()
    dataset_version: str

    @model_validator(mode="after")
    def validate_sample_invariants(self) -> "XGBoostDatasetSample":
        timestamps = (
            self.as_of_time,
            self.target_time,
            self.feature_available_at,
            self.feature_lineage.price.oldest_candle_timestamp,
            self.feature_lineage.price.newest_candle_timestamp,
            self.feature_lineage.price.source_available_at,
        )
        if any(timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("dataset timestamps must be timezone-aware")
        if self.feature_available_at > self.as_of_time:
            raise ValueError("feature_available_at must be <= as_of_time")
        if self.target_time <= self.as_of_time:
            raise ValueError("target_time must be > as_of_time")
        if tuple(self.feature_values) != self.feature_names:
            raise ValueError("feature_values order must exactly match feature_names")
        expected_feature_names = (
            PRICE_FEATURE_NAMES
            if self.dataset_mode == DatasetMode.PRICE_ONLY
            else PRICE_FEATURE_NAMES + DERIVATIVES_FEATURE_NAMES
        )
        if self.feature_names != expected_feature_names:
            raise ValueError("feature_names must exactly match the dataset mode schema")
        forbidden = {"future_close", "future_return", "target_class", "target_time"}
        if forbidden.intersection(self.feature_values):
            raise ValueError("target fields must not appear in feature_values")
        if self.dataset_version != DATASET_VERSION:
            raise ValueError("dataset_version is unsupported")
        if self.feature_status not in {
            FeatureQualityStatus.VALID,
            FeatureQualityStatus.DEGRADED,
        }:
            raise ValueError("feature_status is not eligible for a dataset sample")
        if self.feature_status == FeatureQualityStatus.DEGRADED and (
            "UNSELECTED_PRICE_FEATURES_DEGRADED" not in self.reason_codes
        ):
            raise ValueError("DEGRADED feature status requires an explicit reason")
        if (
            self.exchange_symbol != "BTCUSDT"
            or self.canonical_symbol != "BTC/USDT"
            or self.spot_exchange != "binance"
            or self.timeframe != Timeframe.H4
        ):
            raise ValueError("sample source identity is unsupported")
        if self.close_at_as_of <= 0 or self.future_close <= 0:
            raise ValueError("label prices must be positive")
        expected_return = self.future_close / self.close_at_as_of - Decimal("1")
        if self.future_return != expected_return:
            raise ValueError("future_return does not match label prices")
        expected_threshold = self.label_threshold_k * self.rolling_volatility
        if self.label_threshold != expected_threshold:
            raise ValueError("label_threshold does not match k * rolling_volatility")
        expected_target = TargetClass.NEUTRAL
        if self.future_return > expected_threshold:
            expected_target = TargetClass.BULLISH
        elif self.future_return < -expected_threshold:
            expected_target = TargetClass.BEARISH
        if self.target_class != expected_target:
            raise ValueError("target_class does not match the label contract")
        price_lineage = self.feature_lineage.price
        if (
            price_lineage.source_exchange != self.spot_exchange
            or price_lineage.source_symbol != self.canonical_symbol
            or price_lineage.source_timeframe != self.timeframe.value
            or set(price_lineage.calculator_versions) != set(PRICE_FEATURE_NAMES)
            or any(
                version != PRICE_FEATURE_SET_VERSION
                for version in price_lineage.calculator_versions.values()
            )
        ):
            raise ValueError("price lineage source or calculator schema mismatch")
        if (
            price_lineage.oldest_candle_timestamp
            > price_lineage.newest_candle_timestamp
            or price_lineage.newest_candle_timestamp > price_lineage.source_available_at
            or price_lineage.source_available_at > self.as_of_time
        ):
            raise ValueError("price lineage must be ordered and available by as_of_time")
        expected_available_at = price_lineage.source_available_at
        if self.dataset_mode == DatasetMode.PRICE_PLUS_DERIVATIVES:
            if (
                self.derivatives_exchange != "binance_usdm_futures"
                or self.feature_lineage.derivatives is None
            ):
                raise ValueError("price_plus_derivatives samples require derivatives lineage")
            derivative_lineage = self.feature_lineage.derivatives
            if (
                derivative_lineage.source_exchange != self.derivatives_exchange
                or derivative_lineage.source_symbol != self.canonical_symbol
                or derivative_lineage.sample_count != 20
                or derivative_lineage.cadence_seconds != DERIVATIVES_CADENCE_SECONDS
                or derivative_lineage.cadence_tolerance_seconds
                != DERIVATIVES_CADENCE_TOLERANCE_SECONDS
                or set(derivative_lineage.metric_lineage)
                != {"funding_rate", "open_interest"}
                or set(derivative_lineage.calculator_versions)
                != set(DERIVATIVES_FEATURE_NAMES)
                or any(
                    version != DERIVATIVES_FEATURE_SET_VERSION
                    for version in derivative_lineage.calculator_versions.values()
                )
                or any(
                    len(history) != derivative_lineage.sample_count
                    for history in derivative_lineage.metric_lineage.values()
                )
            ):
                raise ValueError("derivatives lineage source or schema mismatch")
            nested_lineages = [
                lineage
                for metric_history in derivative_lineage.metric_lineage.values()
                for lineage in metric_history
            ]
            if not nested_lineages:
                raise ValueError("derivatives lineage cannot be empty")
            if any(
                timestamp.tzinfo is None
                for lineage in nested_lineages
                for timestamp in (
                    lineage.event_time,
                    lineage.available_at,
                    *lineage.source_timestamps.values(),
                )
            ):
                raise ValueError("derivatives lineage timestamps must be timezone-aware")
            if any(
                lineage.event_time > self.as_of_time
                or lineage.available_at > self.as_of_time
                or any(
                    source_time > self.as_of_time
                    for source_time in lineage.source_timestamps.values()
                )
                for lineage in nested_lineages
            ):
                raise ValueError("derivatives lineage must be available by as_of_time")
            event_times = [lineage.event_time for lineage in nested_lineages]
            if (
                derivative_lineage.oldest_sample_timestamp != min(event_times)
                or derivative_lineage.newest_sample_timestamp != max(event_times)
            ):
                raise ValueError("derivatives lineage bounds must match nested lineage")
            if (
                self.as_of_time - derivative_lineage.newest_sample_timestamp
                > timedelta(minutes=10)
            ):
                raise ValueError("derivatives lineage is stale at as_of_time")
            for metric_history in derivative_lineage.metric_lineage.values():
                if (
                    self.as_of_time - metric_history[-1].event_time
                    > timedelta(minutes=10)
                ):
                    raise ValueError("required derivatives metric is stale at as_of_time")
                for previous, current in zip(
                    metric_history,
                    metric_history[1:],
                    strict=False,
                ):
                    delta_seconds = (current.event_time - previous.event_time).total_seconds()
                    if (
                        abs(delta_seconds - DERIVATIVES_CADENCE_SECONDS)
                        > DERIVATIVES_CADENCE_TOLERANCE_SECONDS
                    ):
                        raise ValueError("derivatives lineage cadence mismatch")
            expected_available_at = max(
                expected_available_at,
                *(lineage.available_at for lineage in nested_lineages),
            )
        elif (
            self.derivatives_exchange is not None
            or self.feature_lineage.derivatives is not None
        ):
            raise ValueError("price_only samples cannot contain derivatives source or lineage")
        if self.feature_available_at != expected_available_at:
            raise ValueError("feature_available_at must exactly match nested lineage")
        return self


class ClassDistribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    counts: FrozenMapping[str, int]
    shares: FrozenMapping[str, float]


class XGBoostDatasetReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DatasetBuildStatus
    dataset_mode: DatasetMode
    dataset_version: str
    label_version: str
    label_threshold_k: Optional[Decimal]
    feature_schema_hash: str
    dataset_checksum: str
    input_candle_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    rejection_counts: FrozenMapping[str, int]
    request_rejection_codes: Tuple[str, ...] = ()
    class_distribution: ClassDistribution
    candidate_class_distributions: FrozenMapping[str, ClassDistribution]
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class XGBoostDatasetBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DatasetBuildStatus
    dataset_mode: DatasetMode
    samples: Tuple[XGBoostDatasetSample, ...]
    report: XGBoostDatasetReport
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_aggregate_integrity(self) -> "XGBoostDatasetBuildResult":
        report = self.report
        if (
            report.status != self.status
            or report.dataset_mode != self.dataset_mode
            or report.dataset_version != DATASET_VERSION
            or report.label_version != LABEL_VERSION
        ):
            raise ValueError("dataset result/report identity mismatch")
        if self.status == DatasetBuildStatus.VALID and (
            report.label_threshold_k is None or report.label_threshold_k <= 0
        ):
            raise ValueError("VALID dataset requires a positive label threshold")
        if any(
            sample.dataset_mode != self.dataset_mode
            or sample.dataset_version != DATASET_VERSION
            or sample.label_threshold_k != report.label_threshold_k
            for sample in self.samples
        ):
            raise ValueError("dataset samples do not match report identity")
        if report.accepted_count != len(self.samples):
            raise ValueError("accepted_count does not match samples")
        if report.rejected_count != report.candidate_count - report.accepted_count:
            raise ValueError("candidate/accepted/rejected counts do not reconcile")
        if sum(report.rejection_counts.values()) != report.rejected_count:
            raise ValueError("rejection reason counts do not reconcile")
        if report.request_rejection_codes and report.candidate_count != 0:
            raise ValueError("request-level rejection cannot report evaluated candidates")
        expected_counts = {target.value: 0 for target in TargetClass}
        for sample in self.samples:
            expected_counts[sample.target_class.value] += 1
        if dict(report.class_distribution.counts) != expected_counts:
            raise ValueError("class distribution counts do not match samples")
        total = len(self.samples)
        expected_shares = {
            target: (count / total if total else 0.0)
            for target, count in expected_counts.items()
        }
        if dict(report.class_distribution.shares) != expected_shares:
            raise ValueError("class distribution shares do not match samples")
        expected_candidate_keys = {
            format(candidate, ".2f") for candidate in LABEL_THRESHOLD_CANDIDATES
        }
        if set(report.candidate_class_distributions) != expected_candidate_keys:
            raise ValueError("candidate class distributions are incomplete")
        for candidate in LABEL_THRESHOLD_CANDIDATES:
            key = format(candidate, ".2f")
            expected_candidate_counts = {target.value: 0 for target in TargetClass}
            for sample in self.samples:
                threshold = candidate * sample.rolling_volatility
                target = TargetClass.NEUTRAL
                if sample.future_return > threshold:
                    target = TargetClass.BULLISH
                elif sample.future_return < -threshold:
                    target = TargetClass.BEARISH
                expected_candidate_counts[target.value] += 1
            candidate_distribution = report.candidate_class_distributions[key]
            if dict(candidate_distribution.counts) != expected_candidate_counts:
                raise ValueError("candidate class distribution does not match samples")
            expected_candidate_shares = {
                target: (count / total if total else 0.0)
                for target, count in expected_candidate_counts.items()
            }
            if dict(candidate_distribution.shares) != expected_candidate_shares:
                raise ValueError("candidate class distribution shares do not match samples")
        expected_start = self.samples[0].as_of_time if self.samples else None
        expected_end = self.samples[-1].as_of_time if self.samples else None
        if report.start_time != expected_start or report.end_time != expected_end:
            raise ValueError("dataset report time range does not match samples")
        if report.feature_schema_hash != feature_schema_hash(self.dataset_mode):
            raise ValueError("feature_schema_hash does not match dataset mode")
        for sample in self.samples:
            expected_id = _sample_id(sample, report.feature_schema_hash)
            if sample.sample_id != expected_id:
                raise ValueError("sample_id does not match deterministic identity")
        if report.dataset_checksum != _dataset_checksum(self.samples):
            raise ValueError("dataset checksum does not match samples")
        if self.status == DatasetBuildStatus.VALID and not self.samples:
            raise ValueError("VALID dataset cannot be empty")
        if self.status == DatasetBuildStatus.REJECTED and self.samples:
            raise ValueError("REJECTED dataset cannot contain samples")
        return self


def _dataset_checksum(samples: Tuple[XGBoostDatasetSample, ...]) -> str:
    payload = [
        sample.model_dump(mode="json", exclude={"ingestion_audit"})
        for sample in samples
    ]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sample_id(sample: XGBoostDatasetSample, schema_hash: str) -> str:
    raw = "|".join(
        (
            DATASET_VERSION,
            sample.dataset_mode.value,
            sample.exchange_symbol,
            sample.canonical_symbol,
            sample.timeframe.value,
            sample.as_of_time.isoformat(),
            sample.target_time.isoformat(),
            schema_hash,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def feature_schema_hash(mode: DatasetMode) -> str:
    feature_names = PRICE_FEATURE_NAMES
    schema: Dict[str, object] = {
        "dataset_version": DATASET_VERSION,
        "label_version": LABEL_VERSION,
        "price_feature_set": PRICE_FEATURE_SET,
        "price_feature_set_version": PRICE_FEATURE_SET_VERSION,
        "feature_names": list(feature_names),
    }
    if mode == DatasetMode.PRICE_PLUS_DERIVATIVES:
        feature_names += DERIVATIVES_FEATURE_NAMES
        schema.update(
            {
                "derivatives_feature_set": DERIVATIVES_FEATURE_SET,
                "derivatives_feature_set_version": DERIVATIVES_FEATURE_SET_VERSION,
                "feature_names": list(feature_names),
                "derivatives_cadence_seconds": DERIVATIVES_CADENCE_SECONDS,
                "derivatives_cadence_tolerance_seconds": (
                    DERIVATIVES_CADENCE_TOLERANCE_SECONDS
                ),
                "excluded_until_point_in_time_lineage": [
                    "futures_basis_momentum_6"
                ],
            }
        )
    encoded = json.dumps(
        schema,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
