"""Out-of-sample evaluation metrics for a direction model, used by an offline training /
walk-forward evaluation script (not part of the live request path).
"""

import math
from typing import Sequence

from packages.prediction.calibration import brier_score, calibration_score_from_ece, expected_calibration_error


def hit_rate(predicted_up: Sequence[bool], actual_up: Sequence[bool]) -> float:
    if len(predicted_up) != len(actual_up):
        raise ValueError("predicted_up and actual_up must be the same length")
    if not predicted_up:
        raise ValueError("cannot score an empty sample")
    correct = sum(1 for p, a in zip(predicted_up, actual_up, strict=True) if p == a)
    return correct / len(predicted_up)


def log_loss(probabilities: Sequence[float], outcomes: Sequence[int], eps: float = 1e-12) -> float:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be the same length")
    if not probabilities:
        raise ValueError("cannot score an empty sample")
    total = 0.0
    for p, y in zip(probabilities, outcomes, strict=True):
        p_clamped = min(max(p, eps), 1 - eps)
        total += -(y * math.log(p_clamped) + (1 - y) * math.log(1 - p_clamped))
    return total / len(probabilities)


class DirectionModelEvaluation:
    def __init__(self, probabilities: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> None:
        self.sample_size = len(probabilities)
        self.brier = brier_score(probabilities, outcomes)
        self.ece = expected_calibration_error(probabilities, outcomes, n_bins)
        self.calibration_score = calibration_score_from_ece(self.ece)
        self.log_loss = log_loss(probabilities, outcomes)
