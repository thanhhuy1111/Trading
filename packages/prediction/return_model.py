"""Expected-return regression model interface + linear implementation.

Same pattern as direction_model.py: inference is plain arithmetic over a serializable
weights artifact, so no training-framework dependency is needed to *use* a registered
model, only to *fit* one offline.
"""

from typing import Dict, List, Protocol

from pydantic import BaseModel


class ReturnModel(Protocol):
    model_version: str

    def predict_expected_return_bps(self, features: Dict[str, float]) -> float: ...


class LinearRegressionWeights(BaseModel):
    model_version: str
    feature_names: List[str]
    coefficients: List[float]
    intercept: float


class LinearReturnModel:
    def __init__(self, weights: LinearRegressionWeights) -> None:
        self._weights = weights

    @property
    def model_version(self) -> str:
        return self._weights.model_version

    def predict_expected_return_bps(self, features: Dict[str, float]) -> float:
        x = [features.get(name, 0.0) for name in self._weights.feature_names]
        return self._weights.intercept + sum(c * v for c, v in zip(self._weights.coefficients, x, strict=True))
