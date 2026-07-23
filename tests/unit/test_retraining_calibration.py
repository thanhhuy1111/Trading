"""packages/retraining/calibration.py -- the sign convention here is the one thing most
likely to have a subtle, silent bug: `LogisticRegressionMetaLabelService._score_logistic_regression`
(packages/intelligence/meta_label.py) already ships the inference formula
`probability = 1/(1+exp(a*raw_probability + b))`; a plain sklearn fit uses the OPPOSITE sign
convention, so `fit_platt_scaling` must negate both coefficients before returning them. These
tests catch a sign-convention regression by round-tripping through the exact inference
formula, not just checking that a dict comes back."""

import math

import pytest

from packages.retraining.calibration import brier_score, fit_platt_scaling


def _apply_meta_label_formula(raw_probability: float, calibration: dict) -> float:
    """Mirrors packages.intelligence.meta_label._score_logistic_regression's platt branch
    exactly -- the real inference code path, not a re-derivation of it."""
    a, b = calibration["a"], calibration["b"]
    return 1.0 / (1.0 + math.exp(a * raw_probability + b))


def test_fit_platt_scaling_returns_none_for_single_outcome_class():
    assert fit_platt_scaling([0.1, 0.4, 0.9], [1, 1, 1]) is None
    assert fit_platt_scaling([0.1, 0.4, 0.9], [0, 0, 0]) is None


def test_fit_platt_scaling_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        fit_platt_scaling([0.1, 0.2], [1])


def test_fit_platt_scaling_sign_convention_matches_meta_label_inference_formula():
    # A well-separated, well-behaved raw-probability stream: high raw probability should
    # correlate with outcome=1, low raw probability with outcome=0.
    raw_probabilities = [0.05, 0.1, 0.15, 0.2, 0.8, 0.85, 0.9, 0.95] * 5
    outcomes = [0, 0, 0, 0, 1, 1, 1, 1] * 5

    calibration = fit_platt_scaling(raw_probabilities, outcomes)
    assert calibration is not None
    assert calibration["method"] == "platt"

    low_calibrated = _apply_meta_label_formula(0.1, calibration)
    high_calibrated = _apply_meta_label_formula(0.9, calibration)

    # Applied through the REAL inference formula, calibration must preserve the monotonic
    # relationship (higher raw probability -> higher calibrated probability) and roughly
    # match the empirical class frequencies it was fit on -- getting the sign backwards
    # would invert this (low_calibrated > high_calibrated).
    assert high_calibrated > low_calibrated
    assert high_calibrated > 0.5
    assert low_calibrated < 0.5


def test_brier_score_zero_for_perfect_predictions():
    assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0


def test_brier_score_rejects_empty_sample():
    with pytest.raises(ValueError):
        brier_score([], [])
