"""Probability calibration -- fit on the VALIDATION split only, never the test split.

Reuses the metric functions already built for the runtime prediction layer
(`packages.prediction.calibration`, `packages.prediction.evaluation`) rather than a second
set of Brier/ECE/log-loss implementations.

Method choice: Platt scaling (a 1-D logistic regression of outcome ~ raw score) is the
default because it is well-behaved on the modest validation-set sizes this pipeline
realistically has (see docs/ALPHA_RESEARCH_RUNBOOK.md for the exact sample sizes any given
run produced); isotonic regression is offered because the plan calls for it, but it needs
materially more validation data to avoid overfitting the calibration curve itself, so
`method="auto"` only switches to it once the validation sample clears a size threshold.
"""

from typing import List, Literal, Protocol

from packages.prediction.calibration import (
    brier_score,
    calibration_score_from_ece,
    expected_calibration_error,
    reliability_buckets,
)
from packages.prediction.evaluation import log_loss
from packages.research.exceptions import InsufficientDataError
from packages.research.models import CalibrationReport

ISOTONIC_SAMPLE_SIZE_THRESHOLD = 500


class ProbabilityScaler(Protocol):
    def calibrate(self, raw_probability: float) -> float: ...


class PlattScaler:
    def __init__(self, a: float, b: float) -> None:
        self.a = a
        self.b = b

    def calibrate(self, raw_probability: float) -> float:
        import math

        z = self.a * raw_probability + self.b
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        ez = math.exp(z)
        return ez / (1.0 + ez)


class IsotonicScaler:
    def __init__(self, model) -> None:  # noqa: ANN001 - sklearn IsotonicRegression, training-time only
        self._model = model

    def calibrate(self, raw_probability: float) -> float:
        return float(self._model.predict([raw_probability])[0])


def fit_platt_scaling(raw_probabilities: List[float], outcomes: List[int]) -> PlattScaler:
    from sklearn.linear_model import LogisticRegression

    if len(raw_probabilities) != len(outcomes):
        raise InsufficientDataError("raw_probabilities and outcomes must be the same length")
    if len(set(outcomes)) < 2:
        raise InsufficientDataError("Cannot fit calibration with only one outcome class present")

    import numpy as np

    X = np.array(raw_probabilities).reshape(-1, 1)
    y = np.array(outcomes)
    clf = LogisticRegression().fit(X, y)
    return PlattScaler(a=float(clf.coef_[0][0]), b=float(clf.intercept_[0]))


def fit_isotonic_scaling(raw_probabilities: List[float], outcomes: List[int]) -> IsotonicScaler:
    from sklearn.isotonic import IsotonicRegression

    if len(raw_probabilities) != len(outcomes):
        raise InsufficientDataError("raw_probabilities and outcomes must be the same length")
    if len(set(outcomes)) < 2:
        raise InsufficientDataError("Cannot fit calibration with only one outcome class present")

    model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    model.fit(raw_probabilities, outcomes)
    return IsotonicScaler(model)


def fit_calibration(
    raw_probabilities: List[float],
    outcomes: List[int],
    method: Literal["auto", "platt", "isotonic"] = "auto",
) -> tuple:
    """Returns (scaler, method_used). Fits ONLY on the data passed in -- callers are
    responsible for passing validation-split data, never test-split data (see
    packages.research.evaluation.run_walk_forward_evaluation for where this is enforced)."""
    resolved_method = method
    if method == "auto":
        resolved_method = "isotonic" if len(outcomes) >= ISOTONIC_SAMPLE_SIZE_THRESHOLD else "platt"

    if resolved_method == "isotonic":
        return fit_isotonic_scaling(raw_probabilities, outcomes), "isotonic"
    return fit_platt_scaling(raw_probabilities, outcomes), "platt"


def build_calibration_report(
    scaler: ProbabilityScaler,
    method: str,
    raw_probabilities: List[float],
    outcomes: List[int],
    n_bins: int = 10,
) -> CalibrationReport:
    calibrated = [scaler.calibrate(p) for p in raw_probabilities]
    ece = expected_calibration_error(calibrated, outcomes, n_bins)
    buckets = reliability_buckets(calibrated, outcomes, n_bins)

    return CalibrationReport(
        method=method,
        fit_on="validation_only",
        sample_size=len(outcomes),
        brier_score=brier_score(calibrated, outcomes),
        log_loss=log_loss(calibrated, outcomes),
        expected_calibration_error=ece,
        calibration_score=calibration_score_from_ece(ece),
        reliability_buckets=[dict(b) for b in buckets],
    )
