"""Unit tests for packages/research/overfitting.py."""

import numpy as np
import pytest

from packages.research.exceptions import InsufficientDataError
from packages.research.overfitting import (
    ExperimentTracker,
    compute_pbo,
    deflated_sharpe_ratio,
    performance_matrix_from_window_breakdowns,
)


def test_experiment_tracker_records_and_counts():
    tracker = ExperimentTracker()
    tracker.record("model", "logistic_regression v1", "hash1")
    tracker.record("hyperparameters", "C=1.0", "hash2")
    tracker.record("hyperparameters", "C=0.5", "hash3")

    assert tracker.total_trials == 3
    assert tracker.count_by_kind("hyperparameters") == 2
    assert tracker.count_by_kind("model") == 1
    assert len(tracker.all_records()) == 3


def test_deflated_sharpe_ratio_is_bounded():
    dsr = deflated_sharpe_ratio(observed_sharpe=1.5, n_trials=5, n_observations=200)
    assert 0.0 <= dsr <= 1.0


def test_deflated_sharpe_ratio_decreases_as_trial_count_increases():
    dsr_few = deflated_sharpe_ratio(observed_sharpe=1.2, n_trials=2, n_observations=200)
    dsr_many = deflated_sharpe_ratio(observed_sharpe=1.2, n_trials=200, n_observations=200)
    assert dsr_many < dsr_few


def test_deflated_sharpe_ratio_higher_for_larger_sharpe():
    low = deflated_sharpe_ratio(observed_sharpe=0.3, n_trials=10, n_observations=200)
    high = deflated_sharpe_ratio(observed_sharpe=2.5, n_trials=10, n_observations=200)
    assert high > low


def test_deflated_sharpe_ratio_raises_on_insufficient_observations():
    with pytest.raises(InsufficientDataError):
        deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=5, n_observations=1)


def test_compute_pbo_in_valid_range_for_noise():
    rng = np.random.default_rng(0)
    matrix = rng.normal(0, 1, size=(20, 6))  # 20 trials, 6 partitions, pure noise
    pbo = compute_pbo(matrix)
    assert 0.0 <= pbo <= 1.0


def test_compute_pbo_low_when_one_trial_dominates_every_partition():
    n_trials, n_partitions = 10, 6
    matrix = np.random.default_rng(1).normal(0, 0.1, size=(n_trials, n_partitions))
    matrix[0, :] = 10.0  # trial 0 is best in literally every partition -> should transfer OOS
    pbo = compute_pbo(matrix)
    assert pbo < 0.5


def test_compute_pbo_raises_on_single_partition():
    with pytest.raises(InsufficientDataError):
        compute_pbo(np.zeros((5, 1)))


def test_compute_pbo_raises_on_single_trial():
    with pytest.raises(InsufficientDataError):
        compute_pbo(np.zeros((1, 5)))


def test_performance_matrix_from_window_breakdowns_builds_correct_shape():
    data = {"trial_a": [1.0, 2.0, 3.0], "trial_b": [0.5, None, 1.5]}
    matrix = performance_matrix_from_window_breakdowns(data)
    assert matrix.shape == (2, 3)
    assert matrix[1, 1] == 0.0  # None -> 0.0


def test_performance_matrix_from_window_breakdowns_raises_on_mismatched_lengths():
    with pytest.raises(InsufficientDataError):
        performance_matrix_from_window_breakdowns({"a": [1.0, 2.0], "b": [1.0]})


def test_performance_matrix_from_window_breakdowns_raises_on_empty():
    with pytest.raises(InsufficientDataError):
        performance_matrix_from_window_breakdowns({})
