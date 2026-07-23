"""Direction classification model interface + a linear (logistic regression) implementation.

Training (fitting the weights from a labeled, point-in-time dataset) is intentionally out
of this module's scope -- see docs/AI_TRADING_ADVISOR_ARCHITECTURE.md for why no trained
artifact ships in this repository yet. Inference only needs plain floats, so it never
requires scikit-learn / xgboost / lightgbm at runtime; those are training-time-only
dependencies (see pyproject.toml `prediction-training` extra).
"""

import math
from typing import Dict, List, Protocol

from pydantic import BaseModel


class DirectionModel(Protocol):
    model_version: str

    def predict_proba(self, features: Dict[str, float]) -> "DirectionProbabilities": ...


class DirectionProbabilities(BaseModel):
    probability_up: float
    probability_down: float
    probability_flat: float


class LogisticRegressionWeights(BaseModel):
    """Serializable artifact produced by an (external, offline) training run."""

    model_version: str
    feature_names: List[str]
    up_coefficients: List[float]
    up_intercept: float
    down_coefficients: List[float]
    down_intercept: float


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


class LogisticRegressionDirectionModel:
    """One-vs-rest logistic regression over UP / DOWN, remainder is FLAT.

    Pure arithmetic inference -- no ML framework dependency at prediction time.
    """

    def __init__(self, weights: LogisticRegressionWeights) -> None:
        self._weights = weights

    @property
    def model_version(self) -> str:
        return self._weights.model_version

    def _score(self, features: Dict[str, float], coefficients: List[float], intercept: float) -> float:
        x = [features.get(name, 0.0) for name in self._weights.feature_names]
        z = intercept + sum(c * v for c, v in zip(coefficients, x, strict=True))
        return _sigmoid(z)

    def predict_proba(self, features: Dict[str, float]) -> DirectionProbabilities:
        p_up_raw = self._score(features, self._weights.up_coefficients, self._weights.up_intercept)
        p_down_raw = self._score(features, self._weights.down_coefficients, self._weights.down_intercept)

        total = p_up_raw + p_down_raw
        if total > 1.0:
            p_up = p_up_raw / total
            p_down = p_down_raw / total
            p_flat = 0.0
        else:
            p_up = p_up_raw
            p_down = p_down_raw
            p_flat = max(0.0, 1.0 - p_up_raw - p_down_raw)

        return DirectionProbabilities(probability_up=p_up, probability_down=p_down, probability_flat=p_flat)
