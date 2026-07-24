"""Fail-closed XGBoost evidence gate and sole artifact publication authority."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict

from packages.common.immutable import FrozenMapping
from packages.domain.enums import RegistryEntryStatus
from packages.registries.models import RegistryEntry
from packages.registries.registry import ArtifactRegistry
from packages.retraining.xgboost_artifacts import (
    XGBoostArtifactManifest,
    XGBoostArtifactWriter,
)
from packages.retraining.xgboost_contracts import (
    DatasetBuildStatus,
    XGBoostDatasetBuildResult,
)
from packages.retraining.xgboost_training import (
    CLASS_ORDER,
    XGBOOST_HYPERPARAMETERS,
    FoldStatus,
    ModelFoldEvaluation,
    TrainingStatus,
    WalkForwardFoldEvaluation,
    XGBoostTrainingResult,
    _build_partitions,
    _calibration_checksum,
    _feature_matrix,
    _flatten,
    _Partition,
    _sample_checksum,
    _timestamp_groups,
    apply_temperature,
    compute_classification_metrics,
    empirical_class_probabilities,
    fit_temperature,
    labels_for_k,
    majority_baseline,
    seeded_random_baseline,
    select_threshold_k,
    validate_probabilities,
    xgboost_walk_forward_trainer,
)

GATE_VERSION = "xgboost_approval_gate_v1"
METRIC_TOLERANCE = 1e-12


class ApprovalDecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalGateDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ApprovalDecisionStatus
    gate_version: str
    reason_codes: Tuple[str, ...] = ()


class ApprovalReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    status: ApprovalDecisionStatus
    gate_version: str
    evaluated_at: datetime
    dataset_checksum: str
    feature_schema_hash: str
    artifact_path: Optional[str] = None
    approval_checksum: Optional[str] = None
    file_checksums: FrozenMapping[str, str]
    reason_codes: Tuple[str, ...] = ()


class ApprovalPublicationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: ApprovalGateDecision
    receipt: ApprovalReceipt
    registry_entry: RegistryEntry
    manifest: Optional[XGBoostArtifactManifest] = None


class XGBoostApprovalGate:
    def evaluate(
        self,
        dataset: XGBoostDatasetBuildResult,
        training: XGBoostTrainingResult,
    ) -> ApprovalGateDecision:
        decision, _ = self._evaluate_with_recomputed_training(dataset, training)
        return decision

    def _evaluate_with_recomputed_training(
        self,
        dataset: XGBoostDatasetBuildResult,
        training: XGBoostTrainingResult,
    ) -> tuple[ApprovalGateDecision, Optional[XGBoostTrainingResult]]:
        reasons: list[str] = []
        try:
            XGBoostDatasetBuildResult.model_validate(dataset.model_dump())
        except ValueError:
            reasons.append("DATASET_CONTRACT_INVALID")
        try:
            training_payload = training.model_dump()
            training_payload["final_model"] = training.final_model
            XGBoostTrainingResult.model_validate(training_payload)
        except ValueError:
            reasons.append("TRAINING_CONTRACT_INVALID")
        if dataset.status != DatasetBuildStatus.VALID:
            reasons.append("DATASET_NOT_VALID")
        if (
            training.status != TrainingStatus.VALID
            or training.report is None
            or training.report.final_recipe is None
            or training.final_model is None
        ):
            reasons.append("TRAINING_NOT_VALID")
            return _decision(reasons), None

        report = training.report
        if report.dataset_checksum != dataset.report.dataset_checksum:
            reasons.append("DATASET_CHECKSUM_MISMATCH")
        if report.feature_schema_hash != dataset.report.feature_schema_hash:
            reasons.append("FEATURE_SCHEMA_MISMATCH")
        if report.dataset_mode != dataset.dataset_mode:
            reasons.append("DATASET_MODE_MISMATCH")
        if (
            report.seed != 42
            or report.class_order != tuple(target.value for target in CLASS_ORDER)
            or dict(report.hyperparameters) != XGBOOST_HYPERPARAMETERS
        ):
            reasons.append("TRAINING_CONFIGURATION_MISMATCH")
        if len(report.folds) != 3:
            reasons.append("FOLD_COUNT_INVALID")
            return _decision(reasons), None

        recomputed_training = xgboost_walk_forward_trainer.train(dataset)
        if (
            recomputed_training.status != TrainingStatus.VALID
            or recomputed_training.report is None
            or recomputed_training.report.model_dump(mode="json")
            != report.model_dump(mode="json")
        ):
            reasons.append("TRAINING_EVIDENCE_MISMATCH")
        if (
            recomputed_training.final_model is None
            or not _native_models_equal(
                training.final_model,
                recomputed_training.final_model,
            )
        ):
            reasons.append("FINAL_MODEL_EVIDENCE_MISMATCH")

        partitions = _build_partitions(dataset.samples)
        for fold, partition in zip(report.folds, partitions, strict=True):
            reasons.extend(_audit_fold(fold, partition))

        reasons.extend(_audit_aggregate(report.folds, report.aggregate_evaluations))
        reasons.extend(_audit_final_recipe(dataset, training))
        return _decision(reasons), recomputed_training


class XGBoostApprovalService:
    """Only this service can create trusted receipts and advance registry approval."""

    def __init__(self, registry: ArtifactRegistry, artifact_root: Path) -> None:
        self._registry = registry
        self._writer = XGBoostArtifactWriter(artifact_root)
        self._receipts: Dict[Tuple[str, str], ApprovalReceipt] = {}
        self._gate = XGBoostApprovalGate()

    def evaluate_and_publish(
        self,
        *,
        model_name: str,
        model_version: str,
        dataset: XGBoostDatasetBuildResult,
        training: XGBoostTrainingResult,
        evaluated_at: datetime,
        code_commit: str,
    ) -> ApprovalPublicationResult:
        if evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        key = (model_name, model_version)
        if key in self._receipts or self._registry.get(*key) is not None:
            raise ValueError("MODEL_VERSION_EXISTS")

        decision, trusted_training = self._gate._evaluate_with_recomputed_training(
            dataset,
            training,
        )
        manifest: Optional[XGBoostArtifactManifest] = None
        if (
            trusted_training is not None
            and trusted_training.status == TrainingStatus.VALID
            and trusted_training.report is not None
            and trusted_training.report.final_recipe is not None
            and trusted_training.final_model is not None
        ):
            manifest = self._writer.write(
                model_name=model_name,
                model_version=model_version,
                dataset=dataset,
                training=trusted_training,
                approval_status=decision.status.value,
                reason_codes=decision.reason_codes,
                gate_version=decision.gate_version,
                evaluated_at=evaluated_at,
                code_commit=code_commit,
            )

        entry = self._registry.register(
            RegistryEntry(
                name=model_name,
                version=model_version,
                status=RegistryEntryStatus.DRAFT,
                artifact_location=manifest.artifact_path if manifest else None,
                artifact_checksum=manifest.approval_checksum if manifest else None,
                code_commit=code_commit,
                configuration_hash=dataset.report.feature_schema_hash,
                dependencies=FrozenMapping(
                    {
                        "dataset_checksum": dataset.report.dataset_checksum,
                        "gate_version": decision.gate_version,
                    }
                ),
                compatible_symbols=("BTC/USDT",),
                compatible_timeframes=("4h",),
            )
        )
        if decision.status == ApprovalDecisionStatus.APPROVED:
            entry = self._registry.transition_status(
                model_name,
                model_version,
                RegistryEntryStatus.RESEARCH_ONLY,
            )
            entry = self._registry.transition_status(
                model_name,
                model_version,
                RegistryEntryStatus.VALIDATED,
            )
            entry = self._registry.transition_status(
                model_name,
                model_version,
                RegistryEntryStatus.APPROVED,
            )
        else:
            entry = self._registry.transition_status(
                model_name,
                model_version,
                RegistryEntryStatus.REJECTED,
                reason_codes=list(decision.reason_codes),
            )

        receipt = ApprovalReceipt(
            model_name=model_name,
            model_version=model_version,
            status=decision.status,
            gate_version=decision.gate_version,
            evaluated_at=evaluated_at,
            dataset_checksum=dataset.report.dataset_checksum,
            feature_schema_hash=dataset.report.feature_schema_hash,
            artifact_path=manifest.artifact_path if manifest else None,
            approval_checksum=manifest.approval_checksum if manifest else None,
            file_checksums=(
                manifest.file_checksums if manifest else FrozenMapping({})
            ),
            reason_codes=decision.reason_codes,
        )
        self._receipts[key] = receipt
        return ApprovalPublicationResult(
            decision=decision,
            receipt=receipt,
            registry_entry=entry,
            manifest=manifest,
        )

    def get_receipt(self, model_name: str, model_version: str) -> Optional[ApprovalReceipt]:
        return self._receipts.get((model_name, model_version))


def _audit_fold(
    fold: WalkForwardFoldEvaluation,
    partition: _Partition,
) -> list[str]:
    reasons: list[str] = []
    fold_prefix = f"FOLD_{fold.fold_number}"
    if fold.status != FoldStatus.VALID:
        return [f"{fold_prefix}_INVALID"]

    train = partition.train
    validation = partition.validation
    test = partition.test
    if (
        fold.train_sample_checksum != _sample_checksum(train)
        or fold.validation_sample_checksum != _sample_checksum(validation)
        or fold.test_sample_checksum != _sample_checksum(test)
    ):
        reasons.append(f"{fold_prefix}_PARTITION_CHECKSUM_MISMATCH")
    try:
        selected_k, train_labels = select_threshold_k(train)
    except ValueError:
        reasons.append(f"{fold_prefix}_THRESHOLD_INVALID")
        return reasons
    validation_labels = labels_for_k(validation, selected_k)
    test_labels = labels_for_k(test, selected_k)
    if fold.selected_k != selected_k:
        reasons.append(f"{fold_prefix}_THRESHOLD_MISMATCH")
    if fold.validation_labels != validation_labels or fold.test_labels != test_labels:
        reasons.append(f"{fold_prefix}_LABEL_MISMATCH")

    try:
        expected_temperature = fit_temperature(
            fold.validation_raw_probabilities,
            fold.validation_labels,
        )
        if fold.temperature is None or not math.isclose(
            fold.temperature,
            expected_temperature,
            rel_tol=0.0,
            abs_tol=METRIC_TOLERANCE,
        ):
            reasons.append(f"{fold_prefix}_CALIBRATION_MISMATCH")
        elif fold.calibration_checksum != _calibration_checksum(
            fold.validation_raw_probabilities,
            fold.validation_labels,
            fold.temperature,
            [sample.sample_id for sample in validation],
        ):
            reasons.append(f"{fold_prefix}_CALIBRATION_CHECKSUM_MISMATCH")
    except ValueError:
        reasons.append(f"{fold_prefix}_CALIBRATION_INVALID")

    required_models = {
        "majority",
        "seeded_random",
        "logistic_regression",
        "xgboost",
    }
    if set(fold.evaluations) != required_models:
        reasons.append(f"{fold_prefix}_COMPARATORS_INCOMPLETE")
        return reasons
    priors = empirical_class_probabilities(train_labels)
    majority_labels, majority_probabilities = majority_baseline(priors, len(test_labels))
    random_labels, random_probabilities = seeded_random_baseline(
        priors,
        len(test_labels),
        42 + fold.fold_number,
    )
    majority = fold.evaluations["majority"]
    random = fold.evaluations["seeded_random"]
    if (
        majority.predicted_labels != majority_labels
        or majority.probabilities != majority_probabilities
    ):
        reasons.append(f"{fold_prefix}_MAJORITY_SEMANTICS_INVALID")
    if (
        random.predicted_labels != random_labels
        or random.probabilities != random_probabilities
    ):
        reasons.append(f"{fold_prefix}_RANDOM_SEMANTICS_INVALID")

    for model_name, evaluation in fold.evaluations.items():
        try:
            validate_probabilities(evaluation.probabilities)
            recomputed = compute_classification_metrics(
                test_labels,
                evaluation.predicted_labels,
                evaluation.probabilities,
            )
            if not _metrics_equal(recomputed, evaluation.metrics):
                reasons.append(f"{fold_prefix}_{model_name.upper()}_METRICS_MISMATCH")
        except ValueError:
            reasons.append(f"{fold_prefix}_{model_name.upper()}_PROBABILITY_INVALID")

    xgboost_metrics = fold.evaluations["xgboost"].metrics
    majority_metrics = majority.metrics
    if xgboost_metrics.balanced_accuracy <= majority_metrics.balanced_accuracy:
        reasons.append(f"{fold_prefix}_BALANCED_ACCURACY_GATE_FAILED")
    if xgboost_metrics.macro_f1 < majority_metrics.macro_f1:
        reasons.append(f"{fold_prefix}_MACRO_F1_GATE_FAILED")
    if xgboost_metrics.mcc <= 0:
        reasons.append(f"{fold_prefix}_MCC_GATE_FAILED")
    if xgboost_metrics.log_loss > majority_metrics.log_loss:
        reasons.append(f"{fold_prefix}_LOG_LOSS_GATE_FAILED")
    if xgboost_metrics.brier_score > majority_metrics.brier_score:
        reasons.append(f"{fold_prefix}_BRIER_GATE_FAILED")
    return reasons


def _audit_aggregate(
    folds: Sequence[WalkForwardFoldEvaluation],
    aggregate: Mapping[str, ModelFoldEvaluation],
) -> list[str]:
    reasons: list[str] = []
    required_models = {
        "majority",
        "seeded_random",
        "logistic_regression",
        "xgboost",
    }
    if set(aggregate) != required_models:
        return ["AGGREGATE_COMPARATORS_INCOMPLETE"]
    actual = tuple(label for fold in folds for label in fold.test_labels)
    for model_name in required_models:
        evaluation = aggregate[model_name]
        predicted = tuple(
            label
            for fold in folds
            for label in fold.evaluations[model_name].predicted_labels
        )
        probabilities = tuple(
            row
            for fold in folds
            for row in fold.evaluations[model_name].probabilities
        )
        if (
            evaluation.predicted_labels != predicted
            or evaluation.probabilities != probabilities
        ):
            reasons.append(f"AGGREGATE_{model_name.upper()}_PREDICTIONS_MISMATCH")
            continue
        recomputed = compute_classification_metrics(actual, predicted, probabilities)
        if not _metrics_equal(recomputed, evaluation.metrics):
            reasons.append(f"AGGREGATE_{model_name.upper()}_METRICS_MISMATCH")
    return reasons


def _audit_final_recipe(
    dataset: XGBoostDatasetBuildResult,
    training: XGBoostTrainingResult,
) -> list[str]:
    reasons: list[str] = []
    assert training.report is not None
    recipe = training.report.final_recipe
    assert recipe is not None
    try:
        from xgboost import XGBClassifier

        if not isinstance(training.final_model, XGBClassifier):
            reasons.append("FINAL_MODEL_TYPE_INVALID")
        elif any(
            training.final_model.get_params().get(key) != value
            for key, value in XGBOOST_HYPERPARAMETERS.items()
        ):
            reasons.append("FINAL_MODEL_CONFIGURATION_MISMATCH")
    except Exception:  # noqa: BLE001
        reasons.append("FINAL_MODEL_CONFIGURATION_INVALID")
    groups = _timestamp_groups(dataset.samples)
    boundary = math.floor(len(groups) * 0.90)
    base_train = _flatten(groups[: max(0, boundary - 1)])
    calibration = _flatten(groups[boundary:])
    try:
        selected_k, _ = select_threshold_k(base_train)
    except ValueError:
        return ["FINAL_THRESHOLD_INVALID"]
    if (
        recipe.selected_k != selected_k
        or recipe.base_train_checksum != _sample_checksum(base_train)
        or recipe.calibration_sample_checksum != _sample_checksum(calibration)
        or recipe.base_train_samples != len(base_train)
        or recipe.calibration_samples != len(calibration)
        or recipe.base_train_start != base_train[0].as_of_time
        or recipe.base_train_end != base_train[-1].as_of_time
        or recipe.calibration_start != calibration[0].as_of_time
        or recipe.calibration_end != calibration[-1].as_of_time
    ):
        reasons.append("FINAL_RECIPE_MISMATCH")
    if max(sample.target_time for sample in base_train) >= calibration[0].as_of_time:
        reasons.append("FINAL_PURGE_OVERLAP_VIOLATION")
    calibration_labels = labels_for_k(calibration, selected_k)
    try:
        raw = training.final_model.predict_proba(_feature_matrix(calibration))
        raw_probabilities = validate_probabilities(raw.tolist())
        expected_temperature = fit_temperature(raw_probabilities, calibration_labels)
        if not math.isclose(
            expected_temperature,
            recipe.temperature,
            rel_tol=0.0,
            abs_tol=METRIC_TOLERANCE,
        ):
            reasons.append("FINAL_CALIBRATION_MISMATCH")
        if recipe.calibration_checksum != _calibration_checksum(
            raw_probabilities,
            calibration_labels,
            recipe.temperature,
            [sample.sample_id for sample in calibration],
        ):
            reasons.append("FINAL_CALIBRATION_CHECKSUM_MISMATCH")
        apply_temperature(raw_probabilities, recipe.temperature)
    except Exception:  # noqa: BLE001
        reasons.append("FINAL_MODEL_VALIDATION_FAILED")
    return reasons


def _metrics_equal(left: BaseModel, right: BaseModel) -> bool:
    left_payload = left.model_dump(mode="json")
    right_payload = right.model_dump(mode="json")
    return _payload_equal(left_payload, right_payload)


def _payload_equal(left: object, right: object) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _payload_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _payload_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(
            left,
            right,
            rel_tol=0.0,
            abs_tol=METRIC_TOLERANCE,
        )
    return left == right


def _native_models_equal(left: object, right: object) -> bool:
    try:
        from xgboost import XGBClassifier

        if not isinstance(left, XGBClassifier) or not isinstance(
            right,
            XGBClassifier,
        ):
            return False
        left_bytes = bytes(left.get_booster().save_raw(raw_format="json"))
        right_bytes = bytes(right.get_booster().save_raw(raw_format="json"))
    except Exception:  # noqa: BLE001
        return False
    return hashlib.sha256(left_bytes).digest() == hashlib.sha256(right_bytes).digest()


def _decision(reasons: Sequence[str]) -> ApprovalGateDecision:
    normalized = tuple(sorted(set(reasons)))
    return ApprovalGateDecision(
        status=(
            ApprovalDecisionStatus.REJECTED
            if normalized
            else ApprovalDecisionStatus.APPROVED
        ),
        gate_version=GATE_VERSION,
        reason_codes=normalized,
    )
