"""Atomic, checksummed native-JSON artifacts for Phase 4 XGBoost models."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Dict, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.common.immutable import FrozenMapping
from packages.retraining.xgboost_contracts import (
    DATASET_VERSION,
    DERIVATIVES_FEATURE_NAMES,
    DERIVATIVES_FEATURE_SET,
    DERIVATIVES_FEATURE_SET_VERSION,
    LABEL_VERSION,
    PRICE_FEATURE_NAMES,
    PRICE_FEATURE_SET,
    PRICE_FEATURE_SET_VERSION,
    DatasetMode,
    XGBoostDatasetBuildResult,
    XGBoostDatasetSample,
)
from packages.retraining.xgboost_training import (
    CLASS_ORDER,
    XGBOOST_HYPERPARAMETERS,
    XGBoostTrainingReport,
    XGBoostTrainingResult,
    apply_temperature,
    validate_probabilities,
)

ARTIFACT_FILES: Tuple[str, ...] = (
    "model.json",
    "metadata.json",
    "feature_schema.json",
    "evaluation.json",
    "approval.json",
)
ARTIFACT_SCHEMA_VERSION = "xgboost_artifact_v1"


class ArtifactApprovalStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class _StrictArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactMetadata(_StrictArtifactPayload):
    artifact_schema_version: Literal["xgboost_artifact_v1"]
    model_name: str
    model_version: str
    exchange_symbol: Literal["BTCUSDT"]
    canonical_symbol: Literal["BTC/USDT"]
    spot_exchange: Literal["binance"]
    derivatives_exchange: Optional[Literal["binance_usdm_futures"]]
    timeframe: Literal["4h"]
    horizon_bars: Literal[1]
    dataset_mode: DatasetMode
    dataset_version: Literal["xgb_direction_dataset_v1"]
    dataset_checksum: str
    label_version: Literal["volatility_band_1bar_v1"]
    label_threshold_k: Decimal
    feature_schema_hash: str
    class_order: Tuple[str, ...]
    temperature: float = Field(gt=0)
    base_train_start: datetime
    base_train_end: datetime
    calibration_start: datetime
    calibration_end: datetime
    xgboost_version: str
    sklearn_version: str
    seed: int
    hyperparameters: Dict[str, object]
    gate_version: str
    code_commit: str
    evaluated_at: datetime

    @field_validator(
        "base_train_start",
        "base_train_end",
        "calibration_start",
        "calibration_end",
        "evaluated_at",
    )
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("artifact timestamps must be timezone-aware")
        return value


class ArtifactFeatureSchema(_StrictArtifactPayload):
    artifact_schema_version: Literal["xgboost_artifact_v1"]
    model_name: str
    model_version: str
    dataset_mode: DatasetMode
    price_feature_set: Literal["standard_v1"]
    price_feature_set_version: Literal["1.0.0"]
    derivatives_feature_set: Optional[Literal["derivatives_v1"]]
    derivatives_feature_set_version: Optional[Literal["1.0.0"]]
    feature_names: Tuple[str, ...]
    feature_dtypes: Tuple[Literal["Decimal"], ...]
    feature_schema_hash: str


class ArtifactEvaluation(_StrictArtifactPayload):
    artifact_schema_version: Literal["xgboost_artifact_v1"]
    model_name: str
    model_version: str
    gate_version: str
    dataset_checksum: str
    feature_schema_hash: str
    training_report: XGBoostTrainingReport


class ArtifactApproval(_StrictArtifactPayload):
    artifact_schema_version: Literal["xgboost_artifact_v1"]
    model_name: str
    model_version: str
    status: ArtifactApprovalStatus
    reason_codes: Tuple[str, ...]
    gate_version: str
    evaluated_at: datetime
    file_checksums: Dict[str, str]

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> "ArtifactApproval":
        if set(self.file_checksums) != set(ARTIFACT_FILES[:-1]):
            raise ValueError("approval checksum manifest is incomplete")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("approval reason codes must be sorted and unique")
        return self


class XGBoostArtifactManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    artifact_path: str
    approval_status: str
    file_checksums: FrozenMapping[str, str]
    approval_checksum: str
    calibrated_roundtrip_max_abs_error: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_manifest(self) -> "XGBoostArtifactManifest":
        if set(self.file_checksums) != set(ARTIFACT_FILES[:-1]):
            raise ValueError("manifest must checksum the four approval inputs")
        if self.approval_status not in {
            ArtifactApprovalStatus.APPROVED,
            ArtifactApprovalStatus.REJECTED,
        }:
            raise ValueError("unsupported artifact approval status")
        return self


class ArtifactVerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    reason_codes: Tuple[str, ...] = ()
    approval: Optional[Dict[str, object]] = None


class XGBoostArtifactWriter:
    def __init__(self, root: Path) -> None:
        self._root = _prepare_artifact_root(root)

    def write(
        self,
        *,
        model_name: str,
        model_version: str,
        dataset: XGBoostDatasetBuildResult,
        training: XGBoostTrainingResult,
        approval_status: str,
        reason_codes: Sequence[str],
        gate_version: str,
        evaluated_at: datetime,
        code_commit: str,
    ) -> XGBoostArtifactManifest:
        if evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if training.report is None or training.report.final_recipe is None:
            raise ValueError("training result has no final model recipe")
        if training.final_model is None:
            raise ValueError("training result has no final model")
        if approval_status not in {
            ArtifactApprovalStatus.APPROVED,
            ArtifactApprovalStatus.REJECTED,
        }:
            raise ValueError("unsupported approval status")
        if not _safe_segment(model_name) or not _safe_segment(model_version):
            raise ValueError("ARTIFACT_ID_INVALID")
        if not code_commit:
            raise ValueError("code_commit is required")

        model_directory = self._root / model_name
        if model_directory.is_symlink():
            raise ValueError("ARTIFACT_PARENT_SYMLINK_FORBIDDEN")
        model_directory.mkdir(parents=False, exist_ok=True)
        if (
            model_directory.is_symlink()
            or model_directory.resolve(strict=True) != model_directory
        ):
            raise ValueError("ARTIFACT_PARENT_SYMLINK_FORBIDDEN")
        target = model_directory / model_version
        if target.exists() or target.is_symlink():
            raise FileExistsError("ARTIFACT_VERSION_EXISTS")
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{model_version}.staging-",
                dir=model_directory,
            )
        )
        try:
            model_path = staging / "model.json"
            training.final_model.save_model(model_path)
            roundtrip_error = _verify_native_roundtrip(
                model_path,
                dataset,
                training,
            )

            feature_names = (
                PRICE_FEATURE_NAMES
                if dataset.dataset_mode == DatasetMode.PRICE_ONLY
                else PRICE_FEATURE_NAMES + DERIVATIVES_FEATURE_NAMES
            )
            metadata = {
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "model_name": model_name,
                "model_version": model_version,
                "exchange_symbol": "BTCUSDT",
                "canonical_symbol": "BTC/USDT",
                "spot_exchange": "binance",
                "derivatives_exchange": (
                    "binance_usdm_futures"
                    if dataset.dataset_mode == DatasetMode.PRICE_PLUS_DERIVATIVES
                    else None
                ),
                "timeframe": "4h",
                "horizon_bars": 1,
                "dataset_mode": dataset.dataset_mode.value,
                "dataset_version": DATASET_VERSION,
                "dataset_checksum": dataset.report.dataset_checksum,
                "label_version": LABEL_VERSION,
                "label_threshold_k": str(
                    training.report.final_recipe.selected_k
                ),
                "feature_schema_hash": dataset.report.feature_schema_hash,
                "class_order": [target.value for target in CLASS_ORDER],
                "temperature": training.report.final_recipe.temperature,
                "base_train_start": (
                    training.report.final_recipe.base_train_start.isoformat()
                ),
                "base_train_end": (
                    training.report.final_recipe.base_train_end.isoformat()
                ),
                "calibration_start": (
                    training.report.final_recipe.calibration_start.isoformat()
                ),
                "calibration_end": (
                    training.report.final_recipe.calibration_end.isoformat()
                ),
                "xgboost_version": training.report.xgboost_version,
                "sklearn_version": training.report.sklearn_version,
                "seed": training.report.seed,
                "hyperparameters": dict(XGBOOST_HYPERPARAMETERS),
                "gate_version": gate_version,
                "code_commit": code_commit,
                "evaluated_at": evaluated_at.isoformat(),
            }
            feature_schema = {
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "model_name": model_name,
                "model_version": model_version,
                "dataset_mode": dataset.dataset_mode.value,
                "price_feature_set": PRICE_FEATURE_SET,
                "price_feature_set_version": PRICE_FEATURE_SET_VERSION,
                "derivatives_feature_set": (
                    DERIVATIVES_FEATURE_SET
                    if dataset.dataset_mode == DatasetMode.PRICE_PLUS_DERIVATIVES
                    else None
                ),
                "derivatives_feature_set_version": (
                    DERIVATIVES_FEATURE_SET_VERSION
                    if dataset.dataset_mode == DatasetMode.PRICE_PLUS_DERIVATIVES
                    else None
                ),
                "feature_names": list(feature_names),
                "feature_dtypes": ["Decimal"] * len(feature_names),
                "feature_schema_hash": dataset.report.feature_schema_hash,
            }
            evaluation = {
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "model_name": model_name,
                "model_version": model_version,
                "gate_version": gate_version,
                "dataset_checksum": dataset.report.dataset_checksum,
                "feature_schema_hash": dataset.report.feature_schema_hash,
                "training_report": training.report.model_dump(mode="json"),
            }
            _write_canonical_json(staging / "metadata.json", metadata)
            _write_canonical_json(staging / "feature_schema.json", feature_schema)
            _write_canonical_json(staging / "evaluation.json", evaluation)

            input_checksums = {
                filename: _file_sha256(staging / filename)
                for filename in ARTIFACT_FILES[:-1]
            }
            approval = {
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "model_name": model_name,
                "model_version": model_version,
                "status": approval_status,
                "reason_codes": sorted(set(reason_codes)),
                "gate_version": gate_version,
                "evaluated_at": evaluated_at.isoformat(),
                "file_checksums": input_checksums,
            }
            _write_canonical_json(staging / "approval.json", approval)
            approval_checksum = _file_sha256(staging / "approval.json")
            os.replace(staging, target)
            return XGBoostArtifactManifest(
                model_name=model_name,
                model_version=model_version,
                artifact_path=str(target),
                approval_status=approval_status,
                file_checksums=FrozenMapping(input_checksums),
                approval_checksum=approval_checksum,
                calibrated_roundtrip_max_abs_error=roundtrip_error,
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise


def verify_artifact_directory(path: Path) -> ArtifactVerificationResult:
    if not path.is_dir():
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("ARTIFACT_DIRECTORY_MISSING",),
        )
    missing = [filename for filename in ARTIFACT_FILES if not (path / filename).is_file()]
    if missing:
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=tuple(
                f"ARTIFACT_FILE_MISSING:{filename}" for filename in sorted(missing)
            ),
        )
    try:
        approval_raw = json.loads(
            (path / "approval.json").read_text(encoding="utf-8")
        )
        approval_payload = ArtifactApproval.model_validate(approval_raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("APPROVAL_JSON_INVALID",),
        )
    approval = approval_payload.model_dump(mode="json")
    expected = approval_payload.file_checksums
    for filename in ARTIFACT_FILES[:-1]:
        if expected.get(filename) != _file_sha256(path / filename):
            return ArtifactVerificationResult(
                valid=False,
                reason_codes=(f"ARTIFACT_CHECKSUM_MISMATCH:{filename}",),
            )
    try:
        model_json = json.loads((path / "model.json").read_text(encoding="utf-8"))
        metadata_payload = ArtifactMetadata.model_validate_json(
            (path / "metadata.json").read_text(encoding="utf-8")
        )
        feature_schema_payload = ArtifactFeatureSchema.model_validate_json(
            (path / "feature_schema.json").read_text(encoding="utf-8")
        )
        evaluation_payload = ArtifactEvaluation.model_validate_json(
            (path / "evaluation.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("ARTIFACT_JSON_INVALID",),
        )
    if not isinstance(model_json, dict):
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("MODEL_JSON_INVALID",),
        )
    metadata = metadata_payload
    feature_schema = feature_schema_payload
    evaluation = evaluation_payload
    training_report = evaluation.training_report
    final_recipe = training_report.final_recipe
    if (
        final_recipe is None
        or metadata.model_name != feature_schema.model_name
        or metadata.model_name != evaluation.model_name
        or metadata.model_name != approval_payload.model_name
        or metadata.model_version != feature_schema.model_version
        or metadata.model_version != evaluation.model_version
        or metadata.model_version != approval_payload.model_version
        or metadata.gate_version != evaluation.gate_version
        or metadata.gate_version != approval_payload.gate_version
        or metadata.dataset_checksum != evaluation.dataset_checksum
        or metadata.dataset_checksum != training_report.dataset_checksum
        or metadata.feature_schema_hash != feature_schema.feature_schema_hash
        or metadata.feature_schema_hash != evaluation.feature_schema_hash
        or metadata.feature_schema_hash != training_report.feature_schema_hash
        or metadata.dataset_mode != feature_schema.dataset_mode
        or metadata.dataset_mode != training_report.dataset_mode
        or metadata.class_order != training_report.class_order
        or metadata.seed != training_report.seed
        or metadata.hyperparameters != dict(training_report.hyperparameters)
        or metadata.temperature != final_recipe.temperature
        or metadata.label_threshold_k != final_recipe.selected_k
        or metadata.base_train_start != final_recipe.base_train_start
        or metadata.base_train_end != final_recipe.base_train_end
        or metadata.calibration_start != final_recipe.calibration_start
        or metadata.calibration_end != final_recipe.calibration_end
        or metadata.xgboost_version != training_report.xgboost_version
        or metadata.sklearn_version != training_report.sklearn_version
        or metadata.evaluated_at != approval_payload.evaluated_at
    ):
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("ARTIFACT_CROSS_FILE_MISMATCH",),
        )
    expected_features = (
        PRICE_FEATURE_NAMES
        if metadata.dataset_mode == DatasetMode.PRICE_ONLY
        else PRICE_FEATURE_NAMES + DERIVATIVES_FEATURE_NAMES
    )
    expected_derivatives_set = (
        None
        if metadata.dataset_mode == DatasetMode.PRICE_ONLY
        else DERIVATIVES_FEATURE_SET
    )
    expected_derivatives_version = (
        None
        if metadata.dataset_mode == DatasetMode.PRICE_ONLY
        else DERIVATIVES_FEATURE_SET_VERSION
    )
    if (
        feature_schema.feature_names != expected_features
        or feature_schema.feature_dtypes != ("Decimal",) * len(expected_features)
        or feature_schema.price_feature_set != PRICE_FEATURE_SET
        or feature_schema.price_feature_set_version != PRICE_FEATURE_SET_VERSION
        or feature_schema.derivatives_feature_set != expected_derivatives_set
        or feature_schema.derivatives_feature_set_version
        != expected_derivatives_version
        or (
            metadata.dataset_mode == DatasetMode.PRICE_ONLY
            and metadata.derivatives_exchange is not None
        )
        or (
            metadata.dataset_mode == DatasetMode.PRICE_PLUS_DERIVATIVES
            and metadata.derivatives_exchange != "binance_usdm_futures"
        )
    ):
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("ARTIFACT_FEATURE_SCHEMA_MISMATCH",),
        )
    return ArtifactVerificationResult(valid=True, approval=approval)


def verify_artifact_receipt(
    path: Path,
    *,
    approval_checksum: str,
    file_checksums: FrozenMapping[str, str],
    expected_status: str,
) -> ArtifactVerificationResult:
    verified = verify_artifact_directory(path)
    if not verified.valid:
        return verified
    if _file_sha256(path / "approval.json") != approval_checksum:
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("APPROVAL_RECEIPT_CHECKSUM_MISMATCH",),
        )
    if dict(file_checksums) != {
        filename: _file_sha256(path / filename)
        for filename in ARTIFACT_FILES[:-1]
    }:
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("ARTIFACT_RECEIPT_FILES_MISMATCH",),
        )
    assert verified.approval is not None
    if verified.approval.get("status") != expected_status:
        return ArtifactVerificationResult(
            valid=False,
            reason_codes=("APPROVAL_RECEIPT_STATUS_MISMATCH",),
        )
    return verified


def _verify_native_roundtrip(
    model_path: Path,
    dataset: XGBoostDatasetBuildResult,
    training: XGBoostTrainingResult,
) -> float:
    from xgboost import XGBClassifier

    assert training.report is not None
    recipe = training.report.final_recipe
    assert recipe is not None
    calibration_samples = tuple(
        sample
        for sample in dataset.samples
        if recipe.calibration_start <= sample.as_of_time <= recipe.calibration_end
    )
    if len(calibration_samples) != recipe.calibration_samples:
        raise ValueError("ARTIFACT_CALIBRATION_WINDOW_MISMATCH")
    matrix = _feature_matrix(dataset.samples)
    before = apply_temperature(
        _probability_rows(training.final_model.predict_proba(matrix)),
        recipe.temperature,
    )
    loaded = XGBClassifier()
    loaded.load_model(model_path)
    after = apply_temperature(
        _probability_rows(loaded.predict_proba(matrix)),
        recipe.temperature,
    )
    maximum_error = max(
        abs(left - right)
        for before_row, after_row in zip(before, after, strict=True)
        for left, right in zip(before_row, after_row, strict=True)
    )
    if maximum_error > 1e-9:
        raise ValueError("MODEL_ROUNDTRIP_PROBABILITY_MISMATCH")
    return maximum_error


def _prepare_artifact_root(root: Path) -> Path:
    absolute = root.absolute()
    for component in (*reversed(absolute.parents), absolute):
        if component.is_symlink():
            raise ValueError("ARTIFACT_ROOT_SYMLINK_FORBIDDEN")
    absolute.mkdir(parents=True, exist_ok=True)
    if absolute.is_symlink() or absolute.resolve(strict=True) != absolute:
        raise ValueError("ARTIFACT_ROOT_SYMLINK_FORBIDDEN")
    return absolute


def _feature_matrix(
    samples: Sequence[XGBoostDatasetSample],
) -> list[list[float]]:
    return [
        [float(sample.feature_values[name]) for name in sample.feature_names]
        for sample in samples
    ]


def _probability_rows(values: object) -> Tuple[Tuple[float, ...], ...]:
    rows = values.tolist() if hasattr(values, "tolist") else values
    if not isinstance(rows, (list, tuple)):
        raise ValueError("PROBABILITY_SHAPE_INVALID")
    return validate_probabilities(rows)


def _write_canonical_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_segment(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value))
