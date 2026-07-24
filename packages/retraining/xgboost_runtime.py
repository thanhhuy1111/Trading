"""Read-only, approved-only runtime inference for Phase 4 XGBoost artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.common.immutable import FrozenMapping
from packages.domain.enums import RegistryEntryStatus
from packages.features.models import FeatureQualityStatus
from packages.retraining.xgboost_approval import (
    ApprovalDecisionStatus,
    ApprovedModelReference,
    XGBoostApprovalService,
)
from packages.retraining.xgboost_artifacts import (
    ArtifactEvaluation,
    ArtifactFeatureSchema,
    ArtifactMetadata,
    verify_artifact_receipt,
)
from packages.retraining.xgboost_contracts import (
    DERIVATIVES_FEATURE_NAMES,
    DERIVATIVES_FEATURE_SET,
    DERIVATIVES_FEATURE_SET_VERSION,
    PRICE_FEATURE_NAMES,
    PRICE_FEATURE_SET,
    PRICE_FEATURE_SET_VERSION,
    DatasetMode,
    TargetClass,
)
from packages.retraining.xgboost_training import (
    apply_temperature,
    validate_probabilities,
)


class PredictionAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class XGBoostRuntimeFeatureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature_snapshot_id: str = Field(min_length=1)
    exchange_symbol: Literal["BTCUSDT"]
    canonical_symbol: Literal["BTC/USDT"]
    spot_exchange: Literal["binance"]
    derivatives_exchange: Optional[Literal["binance_usdm_futures"]] = None
    timeframe: Literal["4h"]
    horizon_bars: Literal[1]
    dataset_mode: DatasetMode
    price_feature_set: str
    price_feature_set_version: str
    derivatives_feature_set: Optional[str] = None
    derivatives_feature_set_version: Optional[str] = None
    feature_schema_hash: str = Field(min_length=1)
    as_of_time: datetime
    available_at: datetime
    quality_status: FeatureQualityStatus
    feature_names: Tuple[str, ...]
    feature_values: FrozenMapping[str, Optional[Decimal]]

    @model_validator(mode="after")
    def validate_snapshot(self) -> "XGBoostRuntimeFeatureSnapshot":
        if self.as_of_time.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("runtime feature timestamps must be timezone-aware")
        if self.available_at > self.as_of_time:
            raise ValueError("feature availability cannot be after as_of_time")
        expected = (
            PRICE_FEATURE_NAMES
            if self.dataset_mode == DatasetMode.PRICE_ONLY
            else PRICE_FEATURE_NAMES + DERIVATIVES_FEATURE_NAMES
        )
        if self.feature_names != expected:
            raise ValueError("feature_names do not match dataset mode")
        if tuple(self.feature_values) != self.feature_names:
            raise ValueError("feature_values must preserve exact feature order")
        if self.dataset_mode == DatasetMode.PRICE_ONLY:
            if (
                self.derivatives_exchange is not None
                or self.derivatives_feature_set is not None
                or self.derivatives_feature_set_version is not None
            ):
                raise ValueError("price-only snapshot cannot declare derivatives inputs")
        elif (
            self.derivatives_exchange != "binance_usdm_futures"
            or self.derivatives_feature_set is None
            or self.derivatives_feature_set_version is None
        ):
            raise ValueError("derivatives mode requires exact derivatives identity")
        return self


class XGBoostRuntimeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str = Field(min_length=1)
    model_version: Optional[str] = None
    snapshot: XGBoostRuntimeFeatureSnapshot


class XGBoostDirectionPrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: PredictionAvailability
    direction: Optional[TargetClass] = None
    probabilities: Optional[FrozenMapping[str, float]] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    model_id: Optional[str] = None
    feature_snapshot_id: Optional[str] = None
    prediction_time: Optional[datetime] = None
    reason_codes: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_availability(self) -> "XGBoostDirectionPrediction":
        available_fields = (
            self.direction,
            self.probabilities,
            self.confidence,
            self.model_id,
            self.feature_snapshot_id,
            self.prediction_time,
        )
        if self.status == PredictionAvailability.AVAILABLE:
            if any(value is None for value in available_fields) or self.reason_codes:
                raise ValueError("AVAILABLE prediction must be complete without reasons")
            assert self.probabilities is not None
            if tuple(self.probabilities) != ("bearish", "neutral", "bullish"):
                raise ValueError("probability keys must match the fixed class order")
            row = tuple(self.probabilities.values())
            validate_probabilities((row,))
            if self.confidence != max(row):
                raise ValueError("confidence must equal max calibrated probability")
            expected_direction = (
                TargetClass.BEARISH,
                TargetClass.NEUTRAL,
                TargetClass.BULLISH,
            )[max(range(3), key=row.__getitem__)]
            if self.direction != expected_direction:
                raise ValueError("direction must be the calibrated probability argmax")
            if self.prediction_time is None or self.prediction_time.tzinfo is None:
                raise ValueError("prediction_time must be timezone-aware")
        elif any(value is not None for value in available_fields):
            raise ValueError("UNAVAILABLE prediction cannot fabricate output fields")
        elif not self.reason_codes:
            raise ValueError("UNAVAILABLE prediction requires a reason code")
        return self


class ApprovedModelRepository:
    """Read-only view over approval-service receipts; never accepts a mutable registry."""

    def __init__(self, approval_service: XGBoostApprovalService) -> None:
        if type(approval_service) is not XGBoostApprovalService:
            raise TypeError("APPROVAL_SERVICE_AUTHORITY_REQUIRED")
        self._approval_service = approval_service

    def resolve(
        self,
        model_name: str,
        model_version: Optional[str],
    ) -> tuple[Optional[ApprovedModelReference], Optional[str]]:
        candidates = tuple(
            reference
            for reference in self._approval_service.list_approved_references()
            if reference.registry_entry.name == model_name
            and (
                model_version is None
                or reference.registry_entry.version == model_version
            )
        )
        if not candidates:
            return None, "NO_APPROVED_MODEL"
        if model_version is None and len(candidates) != 1:
            return None, "AMBIGUOUS_APPROVED_MODEL"
        if len(candidates) != 1:
            return None, "NO_APPROVED_MODEL"
        reference = candidates[0]
        entry = reference.registry_entry
        receipt = reference.receipt
        if (
            entry.status != RegistryEntryStatus.APPROVED
            or receipt.status != ApprovalDecisionStatus.APPROVED
            or entry.name != receipt.model_name
            or entry.version != receipt.model_version
            or entry.artifact_location != receipt.artifact_path
            or entry.artifact_checksum != receipt.approval_checksum
        ):
            return None, "APPROVAL_REFERENCE_MISMATCH"
        return reference, None


class XGBoostRuntime:
    def __init__(self, repository: ApprovedModelRepository) -> None:
        self._repository = repository

    def predict(self, request: XGBoostRuntimeRequest) -> XGBoostDirectionPrediction:
        reference, reason = self._repository.resolve(
            request.model_name,
            request.model_version,
        )
        if reference is None:
            return _unavailable(reason or "NO_APPROVED_MODEL")
        snapshot = request.snapshot
        entry = reference.registry_entry
        receipt = reference.receipt
        if (
            entry.compatible_symbols != (snapshot.canonical_symbol,)
            or entry.compatible_timeframes != (snapshot.timeframe,)
        ):
            return _unavailable("MODEL_COMPATIBILITY_MISMATCH")
        if snapshot.quality_status == FeatureQualityStatus.STALE:
            return _unavailable("FEATURE_DATA_STALE")
        if snapshot.quality_status != FeatureQualityStatus.VALID:
            return _unavailable("FEATURE_STATUS_INVALID")
        if any(value is None for value in snapshot.feature_values.values()):
            return _unavailable("REQUIRED_FEATURE_MISSING")
        if any(
            value is not None and not math.isfinite(float(value))
            for value in snapshot.feature_values.values()
        ):
            return _unavailable("FEATURE_VALUE_INVALID")
        if receipt.artifact_path is None or receipt.approval_checksum is None:
            return _unavailable("APPROVAL_RECEIPT_INCOMPLETE")
        artifact_path = Path(receipt.artifact_path)
        try:
            verified = verify_artifact_receipt(
                artifact_path,
                approval_checksum=receipt.approval_checksum,
                file_checksums=receipt.file_checksums,
                expected_status="APPROVED",
            )
        except (OSError, ValueError, KeyError):
            return _unavailable("ARTIFACT_VERIFICATION_FAILED")
        if not verified.valid:
            return _unavailable("ARTIFACT_VERIFICATION_FAILED")
        try:
            payloads = {
                filename: (artifact_path / filename).read_bytes()
                for filename in (
                    "model.json",
                    "metadata.json",
                    "feature_schema.json",
                    "evaluation.json",
                    "approval.json",
                )
            }
            if hashlib.sha256(payloads["approval.json"]).hexdigest() != (
                receipt.approval_checksum
            ) or any(
                hashlib.sha256(payloads[filename]).hexdigest()
                != receipt.file_checksums[filename]
                for filename in (
                    "model.json",
                    "metadata.json",
                    "feature_schema.json",
                    "evaluation.json",
                )
            ):
                return _unavailable("ARTIFACT_VERIFICATION_FAILED")
            metadata = ArtifactMetadata.model_validate_json(
                payloads["metadata.json"]
            )
            feature_schema = ArtifactFeatureSchema.model_validate_json(
                payloads["feature_schema.json"]
            )
            evaluation = ArtifactEvaluation.model_validate_json(
                payloads["evaluation.json"]
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return _unavailable("ARTIFACT_CONTRACT_INVALID")
        mismatch = _compatibility_mismatch(
            snapshot,
            metadata,
            feature_schema,
            evaluation,
            receipt.dataset_checksum,
        )
        if mismatch is not None:
            return _unavailable(mismatch)
        try:
            from xgboost import XGBClassifier

            model = XGBClassifier()
            model.load_model(bytearray(payloads["model.json"]))
            vector = [
                float(snapshot.feature_values[name])  # type: ignore[arg-type]
                for name in snapshot.feature_names
            ]
            raw = validate_probabilities(model.predict_proba([vector]).tolist())
            calibrated = apply_temperature(
                raw,
                metadata.temperature,
            )
            validated = validate_probabilities(calibrated)
        except Exception:  # noqa: BLE001
            return _unavailable("MODEL_INFERENCE_FAILED")
        row = validated[0]
        predicted_index = max(range(len(row)), key=row.__getitem__)
        direction = (
            TargetClass.BEARISH,
            TargetClass.NEUTRAL,
            TargetClass.BULLISH,
        )[predicted_index]
        probability_map = FrozenMapping(
            {
                "bearish": row[0],
                "neutral": row[1],
                "bullish": row[2],
            }
        )
        return XGBoostDirectionPrediction(
            status=PredictionAvailability.AVAILABLE,
            direction=direction,
            probabilities=probability_map,
            confidence=max(row),
            model_id=f"{entry.name}_{entry.version}",
            feature_snapshot_id=snapshot.feature_snapshot_id,
            prediction_time=snapshot.as_of_time,
        )


def _compatibility_mismatch(
    snapshot: XGBoostRuntimeFeatureSnapshot,
    metadata: ArtifactMetadata,
    feature_schema: ArtifactFeatureSchema,
    evaluation: ArtifactEvaluation,
    receipt_dataset_checksum: str,
) -> Optional[str]:
    if (
        metadata.exchange_symbol != snapshot.exchange_symbol
        or metadata.canonical_symbol != snapshot.canonical_symbol
        or metadata.spot_exchange != snapshot.spot_exchange
        or metadata.derivatives_exchange != snapshot.derivatives_exchange
        or metadata.timeframe != snapshot.timeframe
        or metadata.horizon_bars != snapshot.horizon_bars
    ):
        return "MODEL_COMPATIBILITY_MISMATCH"
    if metadata.dataset_mode != snapshot.dataset_mode:
        return "DATASET_MODE_MISMATCH"
    if (
        metadata.feature_schema_hash != snapshot.feature_schema_hash
        or feature_schema.feature_schema_hash != snapshot.feature_schema_hash
        or evaluation.feature_schema_hash != snapshot.feature_schema_hash
    ):
        return "FEATURE_SCHEMA_MISMATCH"
    if (
        feature_schema.feature_names != snapshot.feature_names
        or tuple(feature_schema.feature_dtypes)
        != ("Decimal",) * len(snapshot.feature_names)
        or snapshot.price_feature_set != PRICE_FEATURE_SET
        or snapshot.price_feature_set_version != PRICE_FEATURE_SET_VERSION
        or snapshot.derivatives_feature_set
        != (
            DERIVATIVES_FEATURE_SET
            if snapshot.dataset_mode == DatasetMode.PRICE_PLUS_DERIVATIVES
            else None
        )
        or snapshot.derivatives_feature_set_version
        != (
            DERIVATIVES_FEATURE_SET_VERSION
            if snapshot.dataset_mode == DatasetMode.PRICE_PLUS_DERIVATIVES
            else None
        )
    ):
        return "FEATURE_CONTRACT_MISMATCH"
    if (
        metadata.dataset_checksum != receipt_dataset_checksum
        or evaluation.dataset_checksum != receipt_dataset_checksum
    ):
        return "DATASET_CHECKSUM_MISMATCH"
    if (
        metadata.temperature <= 0
        or evaluation.training_report.final_recipe is None
        or evaluation.training_report.final_recipe.temperature
        != metadata.temperature
    ):
        return "CALIBRATION_MISSING"
    return None


def _unavailable(reason: str) -> XGBoostDirectionPrediction:
    return XGBoostDirectionPrediction(
        status=PredictionAvailability.UNAVAILABLE,
        reason_codes=(reason,),
    )
