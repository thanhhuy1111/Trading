"""Deterministic walk-forward training and evaluation for the Phase 4 XGBoost model.

This module evaluates four comparators without approving or persisting any model. Threshold
selection, scaling, model fitting, and temperature calibration are confined to their declared
training/validation partitions; test rows are read only after those operations are frozen.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.common.immutable import FrozenMapping
from packages.retraining.xgboost_contracts import (
    LABEL_THRESHOLD_CANDIDATES,
    ClassDistribution,
    DatasetBuildStatus,
    DatasetMode,
    TargetClass,
    XGBoostDatasetBuildResult,
    XGBoostDatasetSample,
)

CLASS_ORDER: Tuple[TargetClass, ...] = (
    TargetClass.BEARISH,
    TargetClass.NEUTRAL,
    TargetClass.BULLISH,
)
CLASS_TO_INDEX = {target: index for index, target in enumerate(CLASS_ORDER)}
SEED = 42
NUM_FOLDS = 3
MIN_TRAIN_SAMPLES = 200
MIN_VALIDATION_SAMPLES = 50
MIN_TEST_SAMPLES = 50
MIN_CLASS_SHARE = 0.10
TARGET_NEUTRAL_SHARE = 0.30
ECE_BINS = 10
PROBABILITY_TOLERANCE = 1e-6
XGBOOST_HYPERPARAMETERS: Dict[str, object] = {
    "objective": "multi:softprob",
    "num_class": 3,
    "n_estimators": 80,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "min_child_weight": 1.0,
    "reg_lambda": 1.0,
    "random_state": SEED,
    "n_jobs": 1,
    "tree_method": "hist",
    "device": "cpu",
    "eval_metric": "mlogloss",
}


class TrainingStatus(str, Enum):
    VALID = "VALID"
    REJECTED = "REJECTED"


class FoldStatus(str, Enum):
    VALID = "VALID"
    REJECTED = "REJECTED"


class ClassificationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    sample_count: int = Field(ge=1)
    accuracy: float = Field(ge=0, le=1)
    balanced_accuracy: float = Field(ge=0, le=1)
    macro_f1: float = Field(ge=0, le=1)
    mcc: float = Field(ge=-1, le=1)
    log_loss: float = Field(ge=0)
    brier_score: float = Field(ge=0)
    ece: float = Field(ge=0, le=1)
    reliability_counts: Tuple[int, ...]
    confusion_matrix: Tuple[Tuple[int, ...], ...]
    class_distribution: ClassDistribution

    @model_validator(mode="after")
    def validate_shape(self) -> "ClassificationMetrics":
        if len(self.reliability_counts) != ECE_BINS:
            raise ValueError("reliability_counts must match ECE_BINS")
        if len(self.confusion_matrix) != 3 or any(
            len(row) != 3 for row in self.confusion_matrix
        ):
            raise ValueError("confusion_matrix must be 3x3")
        if sum(self.reliability_counts) != self.sample_count:
            raise ValueError("reliability counts must sum to sample_count")
        return self


class ModelFoldEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    predicted_labels: Tuple[int, ...]
    probabilities: Tuple[Tuple[float, ...], ...]
    metrics: ClassificationMetrics


class WalkForwardFoldEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    fold_number: int = Field(ge=1, le=NUM_FOLDS)
    status: FoldStatus
    selected_k: Optional[Decimal] = None
    train_start: Optional[datetime] = None
    train_end: Optional[datetime] = None
    validation_start: Optional[datetime] = None
    validation_end: Optional[datetime] = None
    test_start: Optional[datetime] = None
    test_end: Optional[datetime] = None
    train_samples: int = Field(ge=0)
    validation_samples: int = Field(ge=0)
    test_samples: int = Field(ge=0)
    train_class_distribution: ClassDistribution
    validation_class_distribution: ClassDistribution
    test_class_distribution: ClassDistribution
    threshold_candidate_distributions: FrozenMapping[str, ClassDistribution] = Field(
        default_factory=lambda: FrozenMapping({})
    )
    train_sample_checksum: Optional[str] = None
    validation_sample_checksum: Optional[str] = None
    test_sample_checksum: Optional[str] = None
    temperature: Optional[float] = Field(default=None, gt=0)
    calibration_checksum: Optional[str] = None
    validation_labels: Tuple[int, ...] = ()
    validation_raw_probabilities: Tuple[Tuple[float, ...], ...] = ()
    test_labels: Tuple[int, ...] = ()
    evaluations: FrozenMapping[str, ModelFoldEvaluation] = Field(
        default_factory=lambda: FrozenMapping({})
    )
    reason_codes: Tuple[str, ...] = ()


class FinalTrainingRecipe(BaseModel):
    model_config = ConfigDict(frozen=True)

    selected_k: Decimal = Field(gt=0)
    base_train_start: datetime
    base_train_end: datetime
    calibration_start: datetime
    calibration_end: datetime
    base_train_samples: int = Field(ge=MIN_TRAIN_SAMPLES)
    calibration_samples: int = Field(ge=MIN_VALIDATION_SAMPLES)
    base_train_class_distribution: ClassDistribution
    calibration_class_distribution: ClassDistribution
    base_train_checksum: str
    calibration_sample_checksum: str
    calibration_checksum: str
    temperature: float = Field(gt=0)
    model_fit_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_chronology(self) -> "FinalTrainingRecipe":
        if self.base_train_end >= self.calibration_start:
            raise ValueError("base training and calibration windows must be disjoint")
        if self.model_fit_count != 1:
            raise ValueError("final base model must be fit exactly once")
        return self


class XGBoostTrainingReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_mode: DatasetMode
    dataset_checksum: str
    feature_schema_hash: str
    class_order: Tuple[str, ...]
    seed: int
    xgboost_version: str
    sklearn_version: str
    hyperparameters: FrozenMapping[str, object]
    folds: Tuple[WalkForwardFoldEvaluation, ...]
    aggregate_evaluations: FrozenMapping[str, ModelFoldEvaluation]
    final_recipe: Optional[FinalTrainingRecipe] = None


class XGBoostTrainingResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    status: TrainingStatus
    report: Optional[XGBoostTrainingReport] = None
    reason_codes: Tuple[str, ...] = ()
    final_model: Any = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_status(self) -> "XGBoostTrainingResult":
        if self.status == TrainingStatus.VALID:
            if (
                self.report is None
                or self.report.final_recipe is None
                or self.final_model is None
                or len(self.report.folds) != NUM_FOLDS
                or any(fold.status != FoldStatus.VALID for fold in self.report.folds)
            ):
                raise ValueError("VALID training result is incomplete")
        elif self.final_model is not None:
            raise ValueError("REJECTED training result cannot expose a final model")
        return self


class _Partition:
    def __init__(
        self,
        train: Sequence[XGBoostDatasetSample],
        validation: Sequence[XGBoostDatasetSample],
        test: Sequence[XGBoostDatasetSample],
    ) -> None:
        self.train = tuple(train)
        self.validation = tuple(validation)
        self.test = tuple(test)


class XGBoostWalkForwardTrainer:
    def train(self, dataset: XGBoostDatasetBuildResult) -> XGBoostTrainingResult:
        input_reason = _validate_training_input(dataset)
        if input_reason is not None:
            return XGBoostTrainingResult(
                status=TrainingStatus.REJECTED,
                reason_codes=(input_reason,),
            )

        partitions = _build_partitions(dataset.samples)
        folds: List[WalkForwardFoldEvaluation] = []
        for fold_number, partition in enumerate(partitions, start=1):
            folds.append(_evaluate_fold(fold_number, partition))

        report_without_final = _report(
            dataset,
            folds,
            final_recipe=None,
        )
        if any(fold.status != FoldStatus.VALID for fold in folds):
            reasons = tuple(
                sorted(
                    {
                        reason
                        for fold in folds
                        for reason in fold.reason_codes
                    }
                )
            )
            return XGBoostTrainingResult(
                status=TrainingStatus.REJECTED,
                report=report_without_final,
                reason_codes=reasons or ("FOLD_INVALID",),
            )

        final_model, final_recipe, final_reason = _fit_final(dataset.samples)
        if final_reason is not None:
            return XGBoostTrainingResult(
                status=TrainingStatus.REJECTED,
                report=report_without_final,
                reason_codes=(final_reason,),
            )
        assert final_recipe is not None
        return XGBoostTrainingResult(
            status=TrainingStatus.VALID,
            report=_report(dataset, folds, final_recipe),
            final_model=final_model,
        )


def _validate_training_input(
    dataset: XGBoostDatasetBuildResult,
) -> Optional[str]:
    try:
        XGBoostDatasetBuildResult.model_validate(dataset.model_dump())
    except ValueError:
        return "DATASET_CONTRACT_INVALID"
    if dataset.status != DatasetBuildStatus.VALID or not dataset.samples:
        return "DATASET_INVALID"
    if any(sample.dataset_mode != dataset.dataset_mode for sample in dataset.samples):
        return "MIXED_DATASET_MODE"
    timestamps = [sample.as_of_time for sample in dataset.samples]
    if timestamps != sorted(timestamps):
        return "DATASET_ORDER_INVALID"
    if len({sample.sample_id for sample in dataset.samples}) != len(dataset.samples):
        return "DUPLICATE_SAMPLE_ID"
    return None


def _build_partitions(
    samples: Sequence[XGBoostDatasetSample],
) -> Tuple[_Partition, ...]:
    groups = _timestamp_groups(samples)
    total = len(groups)
    boundaries = (
        (0.60, 0.70, 0.80),
        (0.70, 0.80, 0.90),
        (0.80, 0.90, 1.00),
    )
    partitions: List[_Partition] = []
    for train_ratio, validation_ratio, test_ratio in boundaries:
        train_boundary = math.floor(total * train_ratio)
        validation_boundary = math.floor(total * validation_ratio)
        test_boundary = math.floor(total * test_ratio)
        train = _flatten(groups[: max(0, train_boundary - 1)])
        validation = _flatten(
            groups[train_boundary : max(train_boundary, validation_boundary - 1)]
        )
        test = _flatten(groups[validation_boundary:test_boundary])
        partitions.append(_Partition(train, validation, test))
    return tuple(partitions)


def _timestamp_groups(
    samples: Sequence[XGBoostDatasetSample],
) -> List[Tuple[XGBoostDatasetSample, ...]]:
    groups: List[List[XGBoostDatasetSample]] = []
    for sample in samples:
        if not groups or groups[-1][0].as_of_time != sample.as_of_time:
            groups.append([sample])
        else:
            groups[-1].append(sample)
    return [tuple(group) for group in groups]


def _flatten(
    groups: Sequence[Sequence[XGBoostDatasetSample]],
) -> Tuple[XGBoostDatasetSample, ...]:
    return tuple(sample for group in groups for sample in group)


def _evaluate_fold(
    fold_number: int,
    partition: _Partition,
) -> WalkForwardFoldEvaluation:
    reason = _validate_partition(partition)
    if reason is not None:
        return _rejected_fold(fold_number, partition, reason)

    try:
        selected_k, train_labels = select_threshold_k(partition.train)
    except ValueError as exc:
        return _rejected_fold(fold_number, partition, str(exc))
    validation_labels = labels_for_k(partition.validation, selected_k)
    test_labels = labels_for_k(partition.test, selected_k)
    if len(set(validation_labels)) < 3:
        return _rejected_fold(
            fold_number,
            partition,
            "VALIDATION_CLASS_MISSING",
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )
    if len(set(test_labels)) < 3:
        return _rejected_fold(
            fold_number,
            partition,
            "TEST_CLASS_MISSING",
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )

    train_x = _feature_matrix(partition.train)
    validation_x = _feature_matrix(partition.validation)
    test_x = _feature_matrix(partition.test)

    prior = empirical_class_probabilities(train_labels)
    majority_labels, majority_probabilities = majority_baseline(
        prior,
        len(test_labels),
    )
    random_labels, random_probabilities = seeded_random_baseline(
        prior,
        len(test_labels),
        SEED + fold_number,
    )

    try:
        logistic_labels, logistic_probabilities = _fit_logistic(
            train_x,
            train_labels,
            test_x,
        )
    except Exception:  # noqa: BLE001
        return _rejected_fold(
            fold_number,
            partition,
            "LOGISTIC_FIT_FAILED",
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )
    try:
        xgboost_model = _new_xgboost_model()
        xgboost_model.fit(train_x, train_labels)
    except Exception:  # noqa: BLE001
        return _rejected_fold(
            fold_number,
            partition,
            "XGBOOST_FIT_FAILED",
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )
    try:
        validation_prediction = xgboost_model.predict_proba(validation_x)
    except Exception:  # noqa: BLE001
        return _rejected_fold(
            fold_number,
            partition,
            "XGBOOST_PREDICTION_FAILED",
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )
    try:
        validation_raw = _probability_rows(validation_prediction)
        temperature = fit_temperature(validation_raw, validation_labels)
    except ValueError as exc:
        return _rejected_fold(
            fold_number,
            partition,
            str(exc),
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )
    try:
        test_prediction = xgboost_model.predict_proba(test_x)
    except Exception:  # noqa: BLE001
        return _rejected_fold(
            fold_number,
            partition,
            "XGBOOST_PREDICTION_FAILED",
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )
    try:
        xgboost_probabilities = apply_temperature(
            _probability_rows(test_prediction),
            temperature,
        )
        validate_probabilities(xgboost_probabilities)
    except ValueError as exc:
        return _rejected_fold(
            fold_number,
            partition,
            str(exc),
            selected_k,
            train_labels,
            validation_labels,
            test_labels,
        )
    xgboost_labels = tuple(_argmax(row) for row in xgboost_probabilities)

    evaluations = {
        "majority": _model_evaluation(
            "majority",
            test_labels,
            majority_labels,
            majority_probabilities,
        ),
        "seeded_random": _model_evaluation(
            "seeded_random",
            test_labels,
            random_labels,
            random_probabilities,
        ),
        "logistic_regression": _model_evaluation(
            "logistic_regression",
            test_labels,
            logistic_labels,
            logistic_probabilities,
        ),
        "xgboost": _model_evaluation(
            "xgboost",
            test_labels,
            xgboost_labels,
            xgboost_probabilities,
        ),
    }
    return WalkForwardFoldEvaluation(
        fold_number=fold_number,
        status=FoldStatus.VALID,
        selected_k=selected_k,
        train_start=partition.train[0].as_of_time,
        train_end=partition.train[-1].as_of_time,
        validation_start=partition.validation[0].as_of_time,
        validation_end=partition.validation[-1].as_of_time,
        test_start=partition.test[0].as_of_time,
        test_end=partition.test[-1].as_of_time,
        train_samples=len(partition.train),
        validation_samples=len(partition.validation),
        test_samples=len(partition.test),
        train_class_distribution=_class_distribution(train_labels),
        validation_class_distribution=_class_distribution(validation_labels),
        test_class_distribution=_class_distribution(test_labels),
        threshold_candidate_distributions=FrozenMapping(
            _threshold_candidate_distributions(partition.train)
        ),
        train_sample_checksum=_sample_checksum(partition.train),
        validation_sample_checksum=_sample_checksum(partition.validation),
        test_sample_checksum=_sample_checksum(partition.test),
        temperature=temperature,
        calibration_checksum=_calibration_checksum(
            validation_raw,
            validation_labels,
            temperature,
            [sample.sample_id for sample in partition.validation],
        ),
        validation_labels=validation_labels,
        validation_raw_probabilities=validation_raw,
        test_labels=test_labels,
        evaluations=FrozenMapping(evaluations),
    )


def _validate_partition(partition: _Partition) -> Optional[str]:
    if len(partition.train) < MIN_TRAIN_SAMPLES:
        return "TRAIN_PARTITION_UNDERSIZED"
    if len(partition.validation) < MIN_VALIDATION_SAMPLES:
        return "VALIDATION_PARTITION_UNDERSIZED"
    if len(partition.test) < MIN_TEST_SAMPLES:
        return "TEST_PARTITION_UNDERSIZED"
    if (
        max(sample.target_time for sample in partition.train)
        >= partition.validation[0].as_of_time
        or max(sample.target_time for sample in partition.validation)
        >= partition.test[0].as_of_time
    ):
        return "PURGE_OVERLAP_VIOLATION"
    train_times = {sample.as_of_time for sample in partition.train}
    validation_times = {sample.as_of_time for sample in partition.validation}
    test_times = {sample.as_of_time for sample in partition.test}
    if (
        train_times.intersection(validation_times)
        or train_times.intersection(test_times)
        or validation_times.intersection(test_times)
    ):
        return "TIMESTAMP_GROUP_OVERLAP"
    return None


def select_threshold_k(
    samples: Sequence[XGBoostDatasetSample],
) -> Tuple[Decimal, Tuple[int, ...]]:
    candidates: List[Tuple[float, Decimal, Tuple[int, ...]]] = []
    for candidate in LABEL_THRESHOLD_CANDIDATES:
        labels = labels_for_k(samples, candidate)
        counts = [labels.count(index) for index in range(3)]
        total = len(labels)
        shares = [count / total if total else 0.0 for count in counts]
        if total and all(share >= MIN_CLASS_SHARE for share in shares):
            candidates.append(
                (
                    abs(shares[CLASS_TO_INDEX[TargetClass.NEUTRAL]] - TARGET_NEUTRAL_SHARE),
                    candidate,
                    labels,
                )
            )
    if not candidates:
        raise ValueError("THRESHOLD_CLASS_COLLAPSE")
    _, selected_k, labels = min(candidates, key=lambda item: (item[0], item[1]))
    return selected_k, labels


def labels_for_k(
    samples: Sequence[XGBoostDatasetSample],
    threshold_k: Decimal,
) -> Tuple[int, ...]:
    labels: List[int] = []
    for sample in samples:
        threshold = threshold_k * sample.rolling_volatility
        target = TargetClass.NEUTRAL
        if sample.future_return > threshold:
            target = TargetClass.BULLISH
        elif sample.future_return < -threshold:
            target = TargetClass.BEARISH
        labels.append(CLASS_TO_INDEX[target])
    return tuple(labels)


def empirical_class_probabilities(labels: Sequence[int]) -> Tuple[float, ...]:
    if not labels or any(label not in (0, 1, 2) for label in labels):
        raise ValueError("LABELS_INVALID")
    counts = [labels.count(index) for index in range(3)]
    total = len(labels)
    clipped = [max(count / total, 1e-15) for count in counts]
    normalizer = sum(clipped)
    return tuple(value / normalizer for value in clipped)


def majority_baseline(
    priors: Sequence[float],
    sample_count: int,
) -> Tuple[Tuple[int, ...], Tuple[Tuple[float, ...], ...]]:
    validate_probabilities((tuple(priors),))
    majority = max(range(3), key=lambda index: (priors[index], -index))
    return (
        tuple(majority for _ in range(sample_count)),
        tuple(tuple(priors) for _ in range(sample_count)),
    )


def seeded_random_baseline(
    priors: Sequence[float],
    sample_count: int,
    seed: int,
) -> Tuple[Tuple[int, ...], Tuple[Tuple[float, ...], ...]]:
    import numpy as np

    validate_probabilities((tuple(priors),))
    rng = np.random.default_rng(seed)
    labels = tuple(
        int(value)
        for value in rng.choice(3, size=sample_count, p=list(priors)).tolist()
    )
    return labels, tuple(tuple(priors) for _ in range(sample_count))


def fit_temperature(
    raw_probabilities: Sequence[Sequence[float]],
    labels: Sequence[int],
) -> float:
    import numpy as np
    from scipy.optimize import minimize_scalar

    probabilities = validate_probabilities(raw_probabilities)
    if len(probabilities) != len(labels) or not probabilities:
        raise ValueError("CALIBRATION_INPUT_INVALID")
    if set(labels) != {0, 1, 2}:
        raise ValueError("CALIBRATION_CLASS_MISSING")
    logits = np.log(np.clip(np.asarray(probabilities, dtype=float), 1e-15, 1.0))
    centered_logits = logits - np.mean(logits, axis=1, keepdims=True)
    if (
        float(np.max(np.abs(centered_logits))) <= 1e-12
        or float(np.max(np.ptp(centered_logits, axis=0))) <= 1e-12
    ):
        raise ValueError("CALIBRATION_DEGENERATE")
    label_array = np.asarray(labels, dtype=int)

    def objective(log_temperature: float) -> float:
        temperature = math.exp(log_temperature)
        scaled = logits / temperature
        scaled -= np.max(scaled, axis=1, keepdims=True)
        exp_values = np.exp(scaled)
        calibrated = exp_values / np.sum(exp_values, axis=1, keepdims=True)
        chosen = calibrated[np.arange(len(label_array)), label_array]
        return float(-np.mean(np.log(np.clip(chosen, 1e-15, 1.0))))

    result = minimize_scalar(
        objective,
        bounds=(math.log(0.05), math.log(20.0)),
        method="bounded",
        options={"xatol": 1e-12},
    )
    temperature = math.exp(float(result.x))
    if not result.success or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("CALIBRATION_FAILED")
    return temperature


def apply_temperature(
    raw_probabilities: Sequence[Sequence[float]],
    temperature: float,
) -> Tuple[Tuple[float, ...], ...]:
    import numpy as np

    probabilities = validate_probabilities(raw_probabilities)
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("TEMPERATURE_INVALID")
    logits = np.log(np.clip(np.asarray(probabilities, dtype=float), 1e-15, 1.0))
    scaled = logits / temperature
    scaled -= np.max(scaled, axis=1, keepdims=True)
    exp_values = np.exp(scaled)
    calibrated = exp_values / np.sum(exp_values, axis=1, keepdims=True)
    output = tuple(tuple(float(value) for value in row) for row in calibrated.tolist())
    return validate_probabilities(output)


def validate_probabilities(
    probabilities: Sequence[Sequence[float]],
) -> Tuple[Tuple[float, ...], ...]:
    output = tuple(tuple(float(value) for value in row) for row in probabilities)
    if not output:
        raise ValueError("PROBABILITY_EMPTY")
    if any(len(row) != 3 for row in output):
        raise ValueError("PROBABILITY_SHAPE_INVALID")
    for row in output:
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in row):
            raise ValueError("PROBABILITY_VALUE_INVALID")
        if abs(sum(row) - 1.0) > PROBABILITY_TOLERANCE:
            raise ValueError("PROBABILITY_SUM_INVALID")
    return output


def compute_classification_metrics(
    actual_labels: Sequence[int],
    predicted_labels: Sequence[int],
    probabilities: Sequence[Sequence[float]],
) -> ClassificationMetrics:
    import numpy as np
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        confusion_matrix,
        f1_score,
        log_loss,
        matthews_corrcoef,
    )

    probability_rows = validate_probabilities(probabilities)
    actual = tuple(int(label) for label in actual_labels)
    predicted = tuple(int(label) for label in predicted_labels)
    if not actual or len(actual) != len(predicted) or len(actual) != len(probability_rows):
        raise ValueError("METRIC_INPUT_INVALID")
    if any(label not in (0, 1, 2) for label in (*actual, *predicted)):
        raise ValueError("METRIC_LABEL_INVALID")
    probability_array = np.asarray(probability_rows, dtype=float)
    one_hot = np.eye(3, dtype=float)[np.asarray(actual, dtype=int)]
    brier = float(np.mean(np.sum((probability_array - one_hot) ** 2, axis=1)))
    ece, reliability_counts = _expected_calibration_error(actual, probability_rows)
    matrix = confusion_matrix(actual, predicted, labels=[0, 1, 2])
    return ClassificationMetrics(
        sample_count=len(actual),
        accuracy=float(accuracy_score(actual, predicted)),
        balanced_accuracy=float(balanced_accuracy_score(actual, predicted)),
        macro_f1=float(f1_score(actual, predicted, labels=[0, 1, 2], average="macro")),
        mcc=float(matthews_corrcoef(actual, predicted)),
        log_loss=float(log_loss(actual, probability_rows, labels=[0, 1, 2])),
        brier_score=brier,
        ece=ece,
        reliability_counts=reliability_counts,
        confusion_matrix=tuple(
            tuple(int(value) for value in row) for row in matrix.tolist()
        ),
        class_distribution=_class_distribution(actual),
    )


def _expected_calibration_error(
    actual_labels: Sequence[int],
    probabilities: Sequence[Sequence[float]],
) -> Tuple[float, Tuple[int, ...]]:
    bins: List[List[Tuple[float, bool]]] = [[] for _ in range(ECE_BINS)]
    for actual, row in zip(actual_labels, probabilities, strict=True):
        predicted = _argmax(row)
        confidence = row[predicted]
        index = min(ECE_BINS - 1, int(confidence * ECE_BINS))
        bins[index].append((confidence, predicted == actual))
    total = len(actual_labels)
    ece = 0.0
    counts: List[int] = []
    for entries in bins:
        counts.append(len(entries))
        if not entries:
            continue
        average_confidence = sum(entry[0] for entry in entries) / len(entries)
        accuracy = sum(1 for entry in entries if entry[1]) / len(entries)
        ece += len(entries) / total * abs(accuracy - average_confidence)
    return ece, tuple(counts)


def _feature_matrix(samples: Sequence[XGBoostDatasetSample]) -> List[List[float]]:
    return [
        [float(sample.feature_values[name]) for name in sample.feature_names]
        for sample in samples
    ]


def _fit_logistic(
    train_x: Sequence[Sequence[float]],
    train_labels: Sequence[int],
    test_x: Sequence[Sequence[float]],
) -> Tuple[Tuple[int, ...], Tuple[Tuple[float, ...], ...]]:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    scaled_train = scaler.fit_transform(np.asarray(train_x, dtype=float))
    model = LogisticRegression(
        random_state=SEED,
        max_iter=1000,
        solver="lbfgs",
    )
    model.fit(scaled_train, np.asarray(train_labels, dtype=int))
    scaled_test = scaler.transform(np.asarray(test_x, dtype=float))
    probabilities = _probability_rows(model.predict_proba(scaled_test))
    labels = tuple(int(value) for value in model.predict(scaled_test).tolist())
    return labels, validate_probabilities(probabilities)


def _new_xgboost_model() -> Any:
    from xgboost import XGBClassifier

    return XGBClassifier(**XGBOOST_HYPERPARAMETERS)


def _probability_rows(values: Any) -> Tuple[Tuple[float, ...], ...]:
    rows = values.tolist() if hasattr(values, "tolist") else values
    return validate_probabilities(rows)


def _argmax(row: Sequence[float]) -> int:
    return max(range(len(row)), key=lambda index: row[index])


def _model_evaluation(
    model_name: str,
    actual_labels: Sequence[int],
    predicted_labels: Sequence[int],
    probabilities: Sequence[Sequence[float]],
) -> ModelFoldEvaluation:
    probability_rows = validate_probabilities(probabilities)
    return ModelFoldEvaluation(
        model_name=model_name,
        predicted_labels=tuple(predicted_labels),
        probabilities=probability_rows,
        metrics=compute_classification_metrics(
            actual_labels,
            predicted_labels,
            probability_rows,
        ),
    )


def _class_distribution(labels: Sequence[int]) -> ClassDistribution:
    counts = {
        target.value: labels.count(index)
        for index, target in enumerate(CLASS_ORDER)
    }
    total = len(labels)
    shares = {
        target: (count / total if total else 0.0)
        for target, count in counts.items()
    }
    return ClassDistribution(
        counts=FrozenMapping(counts),
        shares=FrozenMapping(shares),
    )


def _empty_distribution() -> ClassDistribution:
    return _class_distribution(())


def _rejected_fold(
    fold_number: int,
    partition: _Partition,
    reason_code: str,
    selected_k: Optional[Decimal] = None,
    train_labels: Sequence[int] = (),
    validation_labels: Sequence[int] = (),
    test_labels: Sequence[int] = (),
) -> WalkForwardFoldEvaluation:
    return WalkForwardFoldEvaluation(
        fold_number=fold_number,
        status=FoldStatus.REJECTED,
        selected_k=selected_k,
        train_start=partition.train[0].as_of_time if partition.train else None,
        train_end=partition.train[-1].as_of_time if partition.train else None,
        validation_start=(
            partition.validation[0].as_of_time if partition.validation else None
        ),
        validation_end=(
            partition.validation[-1].as_of_time if partition.validation else None
        ),
        test_start=partition.test[0].as_of_time if partition.test else None,
        test_end=partition.test[-1].as_of_time if partition.test else None,
        train_samples=len(partition.train),
        validation_samples=len(partition.validation),
        test_samples=len(partition.test),
        train_class_distribution=(
            _class_distribution(train_labels) if train_labels else _empty_distribution()
        ),
        validation_class_distribution=(
            _class_distribution(validation_labels)
            if validation_labels
            else _empty_distribution()
        ),
        test_class_distribution=(
            _class_distribution(test_labels) if test_labels else _empty_distribution()
        ),
        threshold_candidate_distributions=FrozenMapping(
            _threshold_candidate_distributions(partition.train)
        ),
        train_sample_checksum=(
            _sample_checksum(partition.train) if partition.train else None
        ),
        validation_sample_checksum=(
            _sample_checksum(partition.validation) if partition.validation else None
        ),
        test_sample_checksum=(
            _sample_checksum(partition.test) if partition.test else None
        ),
        test_labels=tuple(test_labels),
        reason_codes=(reason_code,),
    )


def _fit_final(
    samples: Sequence[XGBoostDatasetSample],
) -> Tuple[Any, Optional[FinalTrainingRecipe], Optional[str]]:
    groups = _timestamp_groups(samples)
    calibration_boundary = math.floor(len(groups) * 0.90)
    base_train = _flatten(groups[: max(0, calibration_boundary - 1)])
    calibration = _flatten(groups[calibration_boundary:])
    if len(base_train) < MIN_TRAIN_SAMPLES:
        return None, None, "FINAL_BASE_TRAIN_UNDERSIZED"
    if len(calibration) < MIN_VALIDATION_SAMPLES:
        return None, None, "FINAL_CALIBRATION_UNDERSIZED"
    if max(sample.target_time for sample in base_train) >= calibration[0].as_of_time:
        return None, None, "FINAL_PURGE_OVERLAP_VIOLATION"
    try:
        selected_k, base_labels = select_threshold_k(base_train)
    except ValueError as exc:
        return None, None, str(exc)
    calibration_labels = labels_for_k(calibration, selected_k)
    if set(calibration_labels) != {0, 1, 2}:
        return None, None, "FINAL_CALIBRATION_CLASS_MISSING"
    try:
        model = _new_xgboost_model()
        model.fit(_feature_matrix(base_train), base_labels)
    except Exception:  # noqa: BLE001
        return None, None, "FINAL_MODEL_FIT_FAILED"
    try:
        calibration_prediction = model.predict_proba(_feature_matrix(calibration))
    except Exception:  # noqa: BLE001
        return None, None, "FINAL_MODEL_PREDICTION_FAILED"
    try:
        raw_probabilities = _probability_rows(calibration_prediction)
        temperature = fit_temperature(raw_probabilities, calibration_labels)
    except ValueError as exc:
        return None, None, str(exc)
    recipe = FinalTrainingRecipe(
        selected_k=selected_k,
        base_train_start=base_train[0].as_of_time,
        base_train_end=base_train[-1].as_of_time,
        calibration_start=calibration[0].as_of_time,
        calibration_end=calibration[-1].as_of_time,
        base_train_samples=len(base_train),
        calibration_samples=len(calibration),
        base_train_class_distribution=_class_distribution(base_labels),
        calibration_class_distribution=_class_distribution(calibration_labels),
        base_train_checksum=_sample_checksum(base_train),
        calibration_sample_checksum=_sample_checksum(calibration),
        calibration_checksum=_calibration_checksum(
            raw_probabilities,
            calibration_labels,
            temperature,
            [sample.sample_id for sample in calibration],
        ),
        temperature=temperature,
        model_fit_count=1,
    )
    return model, recipe, None


def _report(
    dataset: XGBoostDatasetBuildResult,
    folds: Sequence[WalkForwardFoldEvaluation],
    final_recipe: Optional[FinalTrainingRecipe],
) -> XGBoostTrainingReport:
    import sklearn
    import xgboost

    return XGBoostTrainingReport(
        dataset_mode=dataset.dataset_mode,
        dataset_checksum=dataset.report.dataset_checksum,
        feature_schema_hash=dataset.report.feature_schema_hash,
        class_order=tuple(target.value for target in CLASS_ORDER),
        seed=SEED,
        xgboost_version=xgboost.__version__,
        sklearn_version=sklearn.__version__,
        hyperparameters=FrozenMapping(XGBOOST_HYPERPARAMETERS),
        folds=tuple(folds),
        aggregate_evaluations=FrozenMapping(_aggregate_evaluations(folds)),
        final_recipe=final_recipe,
    )


def _sample_checksum(samples: Sequence[XGBoostDatasetSample]) -> str:
    return _sha256([sample.sample_id for sample in samples])


def _calibration_checksum(
    probabilities: Sequence[Sequence[float]],
    labels: Sequence[int],
    temperature: float,
    sample_ids: Sequence[str],
) -> str:
    return _sha256(
        {
            "raw_probabilities": probabilities,
            "labels": labels,
            "temperature": temperature,
            "sample_ids": sample_ids,
        }
    )


def _threshold_candidate_distributions(
    samples: Sequence[XGBoostDatasetSample],
) -> Dict[str, ClassDistribution]:
    return {
        format(candidate, ".2f"): _class_distribution(
            labels_for_k(samples, candidate)
        )
        for candidate in LABEL_THRESHOLD_CANDIDATES
    }


def _aggregate_evaluations(
    folds: Sequence[WalkForwardFoldEvaluation],
) -> Dict[str, ModelFoldEvaluation]:
    valid_folds = [fold for fold in folds if fold.status == FoldStatus.VALID]
    if not valid_folds:
        return {}
    model_names = tuple(valid_folds[0].evaluations)
    aggregate: Dict[str, ModelFoldEvaluation] = {}
    for model_name in model_names:
        actual = tuple(
            label for fold in valid_folds for label in fold.test_labels
        )
        predicted = tuple(
            label
            for fold in valid_folds
            for label in fold.evaluations[model_name].predicted_labels
        )
        probabilities = tuple(
            row
            for fold in valid_folds
            for row in fold.evaluations[model_name].probabilities
        )
        aggregate[model_name] = _model_evaluation(
            model_name,
            actual,
            predicted,
            probabilities,
        )
    return aggregate


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


xgboost_walk_forward_trainer = XGBoostWalkForwardTrainer()
