"""Unit tests for packages/research/calibration.py."""

import numpy as np
import pytest

from packages.research.calibration import (
    ISOTONIC_SAMPLE_SIZE_THRESHOLD,
    build_calibration_report,
    fit_calibration,
    fit_isotonic_scaling,
    fit_platt_scaling,
)
from packages.research.exceptions import InsufficientDataError


def _synthetic_scores_outcomes(n=300, seed=7):
    rng = np.random.default_rng(seed)
    true_p = rng.uniform(0.05, 0.95, n)
    outcomes = (rng.uniform(0, 1, n) < true_p).astype(int)
    # "raw model score" is a noisy, systematically overconfident version of true_p
    raw = np.clip(true_p * 1.3 - 0.1, 0.001, 0.999)
    return raw.tolist(), outcomes.tolist()


def test_fit_platt_scaling_produces_bounded_output():
    raw, outcomes = _synthetic_scores_outcomes()
    scaler = fit_platt_scaling(raw, outcomes)
    for p in [0.0, 0.2, 0.5, 0.8, 1.0]:
        calibrated = scaler.calibrate(p)
        assert 0.0 <= calibrated <= 1.0


def test_fit_platt_scaling_raises_on_single_class():
    with pytest.raises(InsufficientDataError):
        fit_platt_scaling([0.1, 0.2, 0.3], [1, 1, 1])


def test_fit_platt_scaling_raises_on_length_mismatch():
    with pytest.raises(InsufficientDataError):
        fit_platt_scaling([0.1, 0.2], [1, 0, 1])


def test_fit_isotonic_scaling_produces_bounded_monotonic_output():
    raw, outcomes = _synthetic_scores_outcomes(n=600)
    scaler = fit_isotonic_scaling(raw, outcomes)
    low = scaler.calibrate(0.1)
    high = scaler.calibrate(0.9)
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert low <= high  # isotonic regression is monotonic by construction


def test_fit_calibration_auto_picks_platt_for_small_sample():
    raw, outcomes = _synthetic_scores_outcomes(n=ISOTONIC_SAMPLE_SIZE_THRESHOLD - 50)
    _, method = fit_calibration(raw, outcomes, method="auto")
    assert method == "platt"


def test_fit_calibration_auto_picks_isotonic_for_large_sample():
    raw, outcomes = _synthetic_scores_outcomes(n=ISOTONIC_SAMPLE_SIZE_THRESHOLD + 200)
    _, method = fit_calibration(raw, outcomes, method="auto")
    assert method == "isotonic"


def test_fit_calibration_explicit_method_is_respected():
    raw, outcomes = _synthetic_scores_outcomes(n=1000)
    _, method = fit_calibration(raw, outcomes, method="platt")
    assert method == "platt"


def test_build_calibration_report_has_populated_fields():
    raw, outcomes = _synthetic_scores_outcomes(n=400)
    scaler, method = fit_calibration(raw, outcomes, method="platt")
    report = build_calibration_report(scaler, method, raw, outcomes, n_bins=10)

    assert report.method == "platt"
    assert report.fit_on == "validation_only"
    assert report.sample_size == 400
    assert 0.0 <= report.brier_score <= 1.0
    assert report.log_loss >= 0.0
    assert 0.0 <= report.expected_calibration_error <= 1.0
    assert 0.0 <= report.calibration_score <= 1.0
    assert len(report.reliability_buckets) == 10


def test_reliability_buckets_support_comparing_a_probability_bucket_to_realized_frequency():
    """Plan requirement: a reported probability bucket (e.g. "0.70") must be directly
    comparable against the realized outcome frequency in that bucket."""
    raw, outcomes = _synthetic_scores_outcomes(n=500)
    scaler, method = fit_calibration(raw, outcomes, method="platt")
    report = build_calibration_report(scaler, method, raw, outcomes, n_bins=10)

    bucket_07 = next(
        (b for b in report.reliability_buckets if b["bucket_lower"] <= 0.70 < b["bucket_upper"]), None
    )
    assert bucket_07 is not None
    assert "mean_predicted" in bucket_07
    assert "empirical_frequency" in bucket_07
    assert "count" in bucket_07


def test_calibration_reduces_systematic_overconfidence_bias():
    """The synthetic raw scores are deliberately overconfident (scaled 1.3x); a fitted
    Platt scaler should pull calibrated probabilities closer to the true rate than the
    raw scores were, measured by a lower Brier score after calibration.
    """
    raw, outcomes = _synthetic_scores_outcomes(n=500)
    from packages.prediction.calibration import brier_score

    raw_brier = brier_score(raw, outcomes)
    scaler, method = fit_calibration(raw, outcomes, method="platt")
    calibrated = [scaler.calibrate(p) for p in raw]
    calibrated_brier = brier_score(calibrated, outcomes)

    assert calibrated_brier <= raw_brier
