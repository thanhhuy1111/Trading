"""Offline acceptance tests for Phase 4C walk-forward XGBoost training."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import numpy as np
import pytest
import sklearn.preprocessing

from packages.market_data.models import Candle, DataQualityStatus, Timeframe
from packages.retraining.xgboost_contracts import (
    DatasetBuildStatus,
    DatasetMode,
)
from packages.retraining.xgboost_dataset import xgboost_dataset_builder
from packages.retraining.xgboost_training import (
    CLASS_ORDER,
    FoldStatus,
    TrainingStatus,
    XGBoostTrainingResult,
    apply_temperature,
    empirical_class_probabilities,
    fit_temperature,
    majority_baseline,
    seeded_random_baseline,
    validate_probabilities,
    xgboost_walk_forward_trainer,
)

BASE_TIME = datetime(2020, 1, 1, tzinfo=timezone.utc)
H4 = timedelta(hours=4)


def _market_candles(
    count: int,
    *,
    seed: int = 123,
    constant_return: float | None = None,
) -> list[Candle]:
    rng = np.random.default_rng(seed)
    returns = (
        np.full(count, constant_return, dtype=float)
        if constant_return is not None
        else rng.normal(0.0, 0.004, count)
    )
    prices = [50000.0]
    for value in returns:
        prices.append(prices[-1] * float(np.exp(value)))

    candles: list[Candle] = []
    for index in range(count):
        open_time = BASE_TIME + index * H4
        close_time = open_time + H4 - timedelta(milliseconds=1)
        open_price = Decimal(str(prices[index]))
        close_price = Decimal(str(prices[index + 1]))
        candles.append(
            Candle(
                exchange="binance",
                symbol="BTC/USDT",
                exchange_timestamp=close_time,
                received_timestamp=close_time + timedelta(seconds=1),
                source="offline_seeded_fixture",
                data_quality_status=DataQualityStatus.HEALTHY,
                timeframe=Timeframe.H4,
                open_time=open_time,
                close_time=close_time,
                open_price=open_price,
                high_price=max(open_price, close_price) * Decimal("1.001"),
                low_price=min(open_price, close_price) * Decimal("0.999"),
                close_price=close_price,
                volume=Decimal(str(1000 + abs(returns[index]) * 100000)),
                is_closed=True,
            )
        )
    return candles


def _dataset(count: int = 930, *, constant_return: float | None = None):
    result = xgboost_dataset_builder.build(
        _market_candles(count, constant_return=constant_return),
        mode=DatasetMode.PRICE_ONLY,
        threshold_k=Decimal("0.50"),
    )
    assert result.status == DatasetBuildStatus.VALID
    return result


@pytest.fixture(scope="module")
def trained() -> Iterator[tuple[object, XGBoostTrainingResult]]:
    dataset = _dataset()
    result = xgboost_walk_forward_trainer.train(dataset)
    yield dataset, result


def test_three_expanding_folds_four_models_metrics_and_final_recipe(
    trained: tuple[object, XGBoostTrainingResult],
) -> None:
    dataset, result = trained
    assert result.status == TrainingStatus.VALID
    assert result.report is not None
    assert result.final_model is not None
    assert result.report.class_order == tuple(target.value for target in CLASS_ORDER)
    assert len(result.report.folds) == 3

    samples = dataset.samples  # type: ignore[attr-defined]
    for fold in result.report.folds:
        assert fold.status == FoldStatus.VALID
        assert fold.train_samples >= 200
        assert fold.validation_samples >= 50
        assert fold.test_samples >= 50
        assert fold.train_end is not None
        assert fold.validation_start is not None
        assert fold.validation_end is not None
        assert fold.test_start is not None
        preceding_train_targets = [
            sample.target_time for sample in samples if sample.as_of_time <= fold.train_end
        ]
        preceding_validation_targets = [
            sample.target_time
            for sample in samples
            if fold.validation_start <= sample.as_of_time <= fold.validation_end
        ]
        assert max(preceding_train_targets) < fold.validation_start
        assert max(preceding_validation_targets) < fold.test_start
        assert set(fold.evaluations) == {
            "majority",
            "seeded_random",
            "logistic_regression",
            "xgboost",
        }
        assert fold.temperature is not None
        assert fold.calibration_checksum
        assert fold.train_sample_checksum
        assert fold.validation_sample_checksum
        assert fold.test_sample_checksum
        assert set(fold.threshold_candidate_distributions) == {
            "0.25",
            "0.50",
            "0.75",
            "1.00",
        }
        assert len(fold.test_labels) == fold.test_samples
        for evaluation in fold.evaluations.values():
            assert len(evaluation.predicted_labels) == fold.test_samples
            assert len(evaluation.probabilities) == fold.test_samples
            validate_probabilities(evaluation.probabilities)
            assert evaluation.metrics.sample_count == fold.test_samples
            assert len(evaluation.metrics.confusion_matrix) == 3
            assert sum(evaluation.metrics.reliability_counts) == fold.test_samples
    assert set(result.report.aggregate_evaluations) == {
        "majority",
        "seeded_random",
        "logistic_regression",
        "xgboost",
    }
    aggregate_count = sum(fold.test_samples for fold in result.report.folds)
    assert all(
        evaluation.metrics.sample_count == aggregate_count
        for evaluation in result.report.aggregate_evaluations.values()
    )

    recipe = result.report.final_recipe
    assert recipe is not None
    assert recipe.base_train_end < recipe.calibration_start
    assert recipe.base_train_samples >= 200
    assert recipe.calibration_samples >= 50
    assert recipe.model_fit_count == 1
    assert recipe.base_train_checksum != recipe.calibration_sample_checksum
    assert recipe.calibration_sample_checksum != recipe.calibration_checksum


def test_seed_reproducibility_includes_folds_predictions_and_temperature() -> None:
    dataset = _dataset()
    first = xgboost_walk_forward_trainer.train(dataset)
    second = xgboost_walk_forward_trainer.train(dataset)

    assert first.status == second.status == TrainingStatus.VALID
    assert first.report is not None and second.report is not None
    assert first.report.model_dump(mode="json") == second.report.model_dump(mode="json")


def test_majority_and_seeded_random_baseline_semantics() -> None:
    labels = (0, 0, 0, 1, 2)
    priors = empirical_class_probabilities(labels)
    majority_labels, majority_probabilities = majority_baseline(priors, 8)
    random_labels, random_probabilities = seeded_random_baseline(priors, 8, 43)
    repeated_labels, repeated_probabilities = seeded_random_baseline(priors, 8, 43)

    assert priors == pytest.approx((0.6, 0.2, 0.2))
    assert majority_labels == (0,) * 8
    assert all(row == pytest.approx(priors) for row in majority_probabilities)
    assert random_labels == repeated_labels
    assert random_probabilities == repeated_probabilities
    assert all(row == pytest.approx(priors) for row in random_probabilities)

    tie_priors = empirical_class_probabilities((0, 1, 2))
    tie_labels, _ = majority_baseline(tie_priors, 2)
    assert tie_labels == (0, 0)


def test_temperature_is_validation_only_deterministic_and_round_trips(
    trained: tuple[object, XGBoostTrainingResult],
) -> None:
    _, result = trained
    assert result.report is not None
    for fold in result.report.folds:
        assert fold.temperature is not None
        reproduced = fit_temperature(
            fold.validation_raw_probabilities,
            fold.validation_labels,
        )
        assert reproduced == pytest.approx(fold.temperature, abs=1e-12)
        calibrated = apply_temperature(
            fold.validation_raw_probabilities,
            fold.temperature,
        )
        validate_probabilities(calibrated)

    with pytest.raises(ValueError, match="CALIBRATION_CLASS_MISSING"):
        fit_temperature(((0.8, 0.1, 0.1), (0.7, 0.2, 0.1)), (0, 0))
    with pytest.raises(ValueError, match="CALIBRATION_DEGENERATE"):
        fit_temperature(
            ((1 / 3, 1 / 3, 1 / 3),) * 3,
            (0, 1, 2),
        )


@pytest.mark.parametrize(
    ("probabilities", "reason"),
    [
        ((), "PROBABILITY_EMPTY"),
        (((0.5, 0.5),), "PROBABILITY_SHAPE_INVALID"),
        (((float("nan"), 0.5, 0.5),), "PROBABILITY_VALUE_INVALID"),
        (((float("inf"), 0.0, 0.0),), "PROBABILITY_VALUE_INVALID"),
        (((-0.1, 0.5, 0.6),), "PROBABILITY_VALUE_INVALID"),
        (((0.2, 0.2, 0.2),), "PROBABILITY_SUM_INVALID"),
    ],
)
def test_invalid_probabilities_fail_closed(
    probabilities: tuple[tuple[float, ...], ...],
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        validate_probabilities(probabilities)


def test_undersized_folds_are_all_reported_and_no_model_is_exposed() -> None:
    result = xgboost_walk_forward_trainer.train(_dataset(350))

    assert result.status == TrainingStatus.REJECTED
    assert result.final_model is None
    assert result.report is not None
    assert len(result.report.folds) == 3
    assert all(fold.status == FoldStatus.REJECTED for fold in result.report.folds)
    assert "TRAIN_PARTITION_UNDERSIZED" in result.reason_codes


def test_missing_training_classes_rejects_every_fold_without_fabrication() -> None:
    result = xgboost_walk_forward_trainer.train(
        _dataset(930, constant_return=0.001)
    )

    assert result.status == TrainingStatus.REJECTED
    assert result.final_model is None
    assert result.report is not None
    assert len(result.report.folds) == 3
    assert all(fold.status == FoldStatus.REJECTED for fold in result.report.folds)
    assert "THRESHOLD_CLASS_COLLAPSE" in result.reason_codes


def test_logistic_scaler_fits_train_partitions_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_scaler = sklearn.preprocessing.StandardScaler
    fit_sizes: list[int] = []
    transform_sizes: list[int] = []

    class SpyScaler:
        def __init__(self) -> None:
            self._inner = original_scaler()

        def fit_transform(self, values: np.ndarray) -> np.ndarray:
            fit_sizes.append(len(values))
            return self._inner.fit_transform(values)

        def transform(self, values: np.ndarray) -> np.ndarray:
            transform_sizes.append(len(values))
            return self._inner.transform(values)

    monkeypatch.setattr(sklearn.preprocessing, "StandardScaler", SpyScaler)
    result = xgboost_walk_forward_trainer.train(_dataset())

    assert result.status == TrainingStatus.VALID
    assert result.report is not None
    assert fit_sizes == [fold.train_samples for fold in result.report.folds]
    assert transform_sizes == [fold.test_samples for fold in result.report.folds]


def test_each_xgboost_instance_is_fit_once_including_final_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import packages.retraining.xgboost_training as training_module

    original_factory = training_module._new_xgboost_model
    wrappers: list[object] = []

    class CountingModel:
        def __init__(self) -> None:
            self._inner = original_factory()
            self.fit_count = 0

        def fit(self, values: object, labels: object) -> "CountingModel":
            self.fit_count += 1
            self._inner.fit(values, labels)
            return self

        def predict_proba(self, values: object) -> object:
            return self._inner.predict_proba(values)

    def factory() -> CountingModel:
        model = CountingModel()
        wrappers.append(model)
        return model

    monkeypatch.setattr(training_module, "_new_xgboost_model", factory)
    result = xgboost_walk_forward_trainer.train(_dataset())

    assert result.status == TrainingStatus.VALID
    assert len(wrappers) == 4
    assert all(model.fit_count == 1 for model in wrappers)  # type: ignore[attr-defined]


def test_invalid_model_probability_and_tampered_dataset_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import packages.retraining.xgboost_training as training_module

    class InvalidProbabilityModel:
        def fit(self, values: object, labels: object) -> "InvalidProbabilityModel":
            return self

        def predict_proba(self, values: object) -> list[list[float]]:
            return [[0.5, 0.5] for _ in range(len(values))]  # type: ignore[arg-type]

    monkeypatch.setattr(
        training_module,
        "_new_xgboost_model",
        InvalidProbabilityModel,
    )
    rejected = xgboost_walk_forward_trainer.train(_dataset())
    assert rejected.status == TrainingStatus.REJECTED
    assert rejected.final_model is None
    assert "PROBABILITY_SHAPE_INVALID" in rejected.reason_codes
    assert rejected.report is not None
    assert len(rejected.report.folds) == 3

    class RaisingModel:
        def fit(self, values: object, labels: object) -> None:
            raise ValueError("third party message with spaces")

    monkeypatch.setattr(training_module, "_new_xgboost_model", RaisingModel)
    external_rejected = xgboost_walk_forward_trainer.train(_dataset())
    assert external_rejected.status == TrainingStatus.REJECTED
    assert external_rejected.reason_codes == ("XGBOOST_FIT_FAILED",)

    dataset = _dataset()
    tampered_report = dataset.report.model_copy(
        update={"dataset_checksum": "0" * 64}
    )
    tampered = dataset.model_copy(update={"report": tampered_report})
    contract_rejected = xgboost_walk_forward_trainer.train(tampered)
    assert contract_rejected.status == TrainingStatus.REJECTED
    assert contract_rejected.reason_codes == ("DATASET_CONTRACT_INVALID",)
