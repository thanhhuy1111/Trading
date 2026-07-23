"""Phase 4.1: meta-label services.

`PassThroughMetaLabelService` is the only meta-label service actually active anywhere in this
task — it does not pretend to be trained ML. `LogisticRegressionMetaLabelService` and
`TreeMetaLabelService` define the real interface and artifact format Checkpoint 3's retraining
workflow will populate, with genuine (if simple, dependency-free) inference math — but with no
model actually registered in this task, both correctly fall back to the same honest
NOT_AVAILABLE / DEFER_TO_EXISTING_RULES response as the pass-through service. No model here is
claimed to be accurate or approved (Section 9.1: "Do not require those models to be accurate
or approved in this task").
"""

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from packages.candidates.models import TradeCandidate
from packages.domain.entities import ModelPrediction
from packages.domain.enums import MetaLabelDecision, ModelType
from packages.registries.models import RegistryEntry
from packages.registries.registry import ArtifactRegistry

FEATURE_VERSION = "standard_v1"
LABEL_VERSION = "meta_label_v1"


class PassThroughMetaLabelService:
    """The baseline. Never scores, never filters — every candidate defers to whatever the
    rule-based DecisionService/StrategyRouter already decided upstream."""

    model_type = ModelType.PASS_THROUGH
    model_version = "n/a"

    async def predict(self, candidate: TradeCandidate) -> ModelPrediction:
        return ModelPrediction(
            candidate_id=candidate.candidate_id,
            model_type=self.model_type,
            model_version=self.model_version,
            feature_version=FEATURE_VERSION,
            label_version=LABEL_VERSION,
            probability=None,
            decision=MetaLabelDecision.DEFER_TO_EXISTING_RULES,
            reason_codes=["TRAINED_MODEL_NOT_AVAILABLE"],
            status="BASELINE_ONLY",
        )


class _RegistryBackedMetaLabelService:
    """Shared lookup/fallback logic for the two "real interface, no model yet" services below.
    Both require an APPROVED or RESEARCH_ONLY registry entry compatible with the candidate's
    (symbol, timeframe) before they'll even attempt inference — a missing entry is not an
    error, it's the expected, common case in this task and returns the same honest baseline
    response as PassThroughMetaLabelService."""

    model_type: ModelType

    def __init__(
        self, registry: ArtifactRegistry, artifact_loader: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        self._registry = registry
        # Injected so tests can supply a fixture artifact dict without touching a filesystem —
        # production wiring would load JSON from RegistryEntry.artifact_location.
        self._artifact_loader = artifact_loader or (lambda location: None)

    def _unavailable(self, candidate: TradeCandidate, reason: str) -> ModelPrediction:
        return ModelPrediction(
            candidate_id=candidate.candidate_id,
            model_type=self.model_type,
            model_version="n/a",
            feature_version=FEATURE_VERSION,
            label_version=LABEL_VERSION,
            probability=None,
            decision=MetaLabelDecision.DEFER_TO_EXISTING_RULES,
            reason_codes=[reason],
            status="BASELINE_ONLY",
        )

    def _find_entry(self, candidate: TradeCandidate) -> Optional[RegistryEntry]:
        from packages.domain.enums import RegistryEntryStatus
        candidates = [
            e for e in self._registry.find_compatible(symbol=candidate.symbol, timeframe=candidate.timeframe)
            if e.status in (RegistryEntryStatus.APPROVED, RegistryEntryStatus.RESEARCH_ONLY)
        ]
        return candidates[0] if candidates else None


class LogisticRegressionMetaLabelService(_RegistryBackedMetaLabelService):
    """Artifact format (JSON), what Checkpoint 3's retraining workflow must produce:

        {
          "feature_names": [...],           # order matches "coefficients"
          "coefficients": [float, ...],
          "intercept": float,
          "calibration": {"method": "platt", "a": float, "b": float} | null,
          "decision_threshold": float        # default 0.5
        }

    probability = sigmoid(intercept + sum(coef_i * feature_i)), then Platt-scaled if
    calibration is present. No feature imputation — a missing required feature makes the
    candidate NOT_AVAILABLE for this model, never a fabricated default value.
    """

    model_type = ModelType.LOGISTIC_REGRESSION

    async def predict(self, candidate: TradeCandidate) -> ModelPrediction:
        entry = self._find_entry(candidate)
        if entry is None:
            return self._unavailable(candidate, "TRAINED_MODEL_NOT_AVAILABLE")

        if entry.artifact_location is None:
            return self._unavailable(candidate, "MODEL_ARTIFACT_UNREADABLE")
        artifact = self._artifact_loader(entry.artifact_location)
        if artifact is None:
            return self._unavailable(candidate, "MODEL_ARTIFACT_UNREADABLE")

        try:
            probability, decision = _score_logistic_regression(artifact, candidate.feature_snapshot)
        except _MissingFeatureError as exc:
            pred = self._unavailable(candidate, "REQUIRED_FEATURE_MISSING")
            pred.reason_codes.append(str(exc))
            return pred

        from decimal import Decimal
        return ModelPrediction(
            candidate_id=candidate.candidate_id, model_type=self.model_type, model_version=entry.version,
            feature_version=FEATURE_VERSION, label_version=LABEL_VERSION,
            probability=Decimal(str(round(probability, 6))), decision=decision,
            reason_codes=[], status="INFERRED",
        )


class TreeMetaLabelService(_RegistryBackedMetaLabelService):
    """Artifact format (JSON):

        {
          "feature_names": [...],
          "nodes": [
            {"feature_index": int, "threshold": float, "left": int, "right": int} |
            {"leaf_value": float}
          ]
        }

    Traversal starts at node 0; `left` is taken when feature_value <= threshold. leaf_value is
    treated as a probability directly (no separate calibration step defined for this baseline
    format — Checkpoint 3 may add one when it actually trains a tree model).
    """

    model_type = ModelType.TREE_MODEL

    async def predict(self, candidate: TradeCandidate) -> ModelPrediction:
        entry = self._find_entry(candidate)
        if entry is None:
            return self._unavailable(candidate, "TRAINED_MODEL_NOT_AVAILABLE")

        if entry.artifact_location is None:
            return self._unavailable(candidate, "MODEL_ARTIFACT_UNREADABLE")
        artifact = self._artifact_loader(entry.artifact_location)
        if artifact is None:
            return self._unavailable(candidate, "MODEL_ARTIFACT_UNREADABLE")

        try:
            probability = _score_tree(artifact, candidate.feature_snapshot)
        except _MissingFeatureError as exc:
            pred = self._unavailable(candidate, "REQUIRED_FEATURE_MISSING")
            pred.reason_codes.append(str(exc))
            return pred

        decision = MetaLabelDecision.ACCEPT if probability > 0.5 else MetaLabelDecision.REJECT
        from decimal import Decimal
        return ModelPrediction(
            candidate_id=candidate.candidate_id, model_type=self.model_type, model_version=entry.version,
            feature_version=FEATURE_VERSION, label_version=LABEL_VERSION,
            probability=Decimal(str(round(probability, 6))), decision=decision,
            reason_codes=[], status="INFERRED",
        )


class _MissingFeatureError(Exception):
    pass


def _feature_vector(feature_names: List[str], feature_snapshot: Dict[str, Optional[str]]) -> List[float]:
    vector = []
    for name in feature_names:
        raw = feature_snapshot.get(name)
        if raw is None:
            raise _MissingFeatureError(f"MISSING_FEATURE:{name}")
        vector.append(float(raw))
    return vector


def _score_logistic_regression(
    artifact: Dict[str, Any], feature_snapshot: Dict[str, Optional[str]],
) -> Tuple[float, MetaLabelDecision]:
    features = _feature_vector(artifact["feature_names"], feature_snapshot)
    logit = artifact["intercept"] + sum(c * f for c, f in zip(artifact["coefficients"], features, strict=True))
    probability = 1.0 / (1.0 + math.exp(-logit))

    calibration = artifact.get("calibration")
    if calibration and calibration.get("method") == "platt":
        a, b = calibration["a"], calibration["b"]
        probability = 1.0 / (1.0 + math.exp(a * probability + b))

    threshold = artifact.get("decision_threshold", 0.5)
    decision = MetaLabelDecision.ACCEPT if probability > threshold else MetaLabelDecision.REJECT
    return probability, decision


def _score_tree(artifact: Dict[str, Any], feature_snapshot: Dict[str, Optional[str]]) -> float:
    features = _feature_vector(artifact["feature_names"], feature_snapshot)
    nodes = artifact["nodes"]
    idx = 0
    for _ in range(len(nodes) + 1):  # bounded traversal — malformed artifacts can't infinite-loop
        node = nodes[idx]
        if "leaf_value" in node:
            return float(node["leaf_value"])
        value = features[node["feature_index"]]
        idx = node["left"] if value <= node["threshold"] else node["right"]
    raise ValueError("MALFORMED_TREE_ARTIFACT: traversal did not terminate at a leaf")
