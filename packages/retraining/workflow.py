"""Phase 12: retraining workflow.

Stages: dataset selection -> checksum -> feature generation -> label generation -> time-series
split with purge/embargo (reusing `packages.backtest.walk_forward.WalkForwardRunner`, the same
utility Checkpoint 1/2's campaigns already use, rather than a second split implementation) ->
training -> validation -> calibration -> test -> artifact + registry publication (always
RESEARCH_ONLY, never APPROVED) -> evidence review request (always INSUFFICIENT, explicitly
awaiting human review).

No large hyperparameter search (Section 4, rule 18): this fits exactly one small logistic-
regression model via a bounded number of full-batch gradient-descent steps, using the exact
artifact format `packages.intelligence.meta_label.LogisticRegressionMetaLabelService` already
documents and can load. A small fixture-based training smoke test is the acceptance bar here,
not an accuracy campaign (Section 2: "do not optimize toward profitable backtest results in
this task") - `tests/unit/test_retraining_workflow.py` only asserts the workflow runs
end-to-end and produces a well-formed, RESEARCH_ONLY-only result, never a specific accuracy
number.

Labels are intentionally forward-looking (next-bar return sign) - that is what a supervised
label IS. This is distinct from and does not violate rule 4's "no future-derived FEATURES":
the feature vector for bar i only ever reads candles up to and including bar i.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from packages.backtest.walk_forward import WalkForwardRunner, walk_forward_runner
from packages.domain.enums import ModelType, RegistryEntryStatus
from packages.evidence.models import EvidenceKey, EvidenceRecord, EvidenceStatus
from packages.evidence.store import EvidenceStore
from packages.features.models import FeatureComputationRequest
from packages.features.pipeline import feature_pipeline
from packages.market_data.models import Candle, Timeframe
from packages.registries.models import RegistryEntry
from packages.registries.registry import ArtifactRegistry

FEATURE_VERSION = "standard_v1"
LABEL_VERSION = "meta_label_v1"
FEATURE_NAMES = ["rsi_14"]
FEATURE_LOOKBACK_WINDOW = 60
MIN_LOOKBACK_BARS = 15  # rsi_14 needs period(14)+1
MAX_TRAINING_ITERATIONS = 200  # bounded - no large hyperparameter search
DEFAULT_LEARNING_RATE = 0.1


@dataclass
class _Row:
    timestamp: datetime
    features: List[float]
    label: int


@dataclass
class RetrainingJobResult:
    job_id: UUID
    dataset_checksum: str
    symbol: str
    timeframe: str
    feature_version: str
    label_version: str
    model_type: ModelType
    model_version: str
    stages_completed: List[str]
    train_sample_count: int
    validation_sample_count: int
    test_sample_count: int
    train_accuracy: float
    validation_accuracy: float
    test_accuracy: float
    registry_status: RegistryEntryStatus
    evidence_key: EvidenceKey
    reason_codes: List[str] = field(default_factory=list)


class RetrainingWorkflow:
    def __init__(
        self,
        model_registry: ArtifactRegistry,
        evidence_store: EvidenceStore,
        fold_runner: WalkForwardRunner = walk_forward_runner,
        max_iterations: int = MAX_TRAINING_ITERATIONS,
        learning_rate: float = DEFAULT_LEARNING_RATE,
    ) -> None:
        self._model_registry = model_registry
        self._evidence_store = evidence_store
        self._fold_runner = fold_runner
        self._max_iterations = max_iterations
        self._learning_rate = learning_rate

    async def run_training_job(
        self,
        candles: List[Candle],
        symbol: str,
        timeframe: Timeframe,
        strategy_name: str,
        strategy_version: str,
        strategy_config_hash: str,
        gate_version: str = "gate_v1",
        code_commit: str = "n/a",
        session_id: Optional[UUID] = None,
    ) -> RetrainingJobResult:
        stages: List[str] = []
        job_id = uuid4()

        # Stage 1: dataset selection - candles are caller-provided; this workflow never fetches
        # anything live itself.
        sorted_candles = sorted(candles, key=lambda c: c.close_time)
        stages.append("DATASET_SELECTED")
        if len(sorted_candles) < MIN_LOOKBACK_BARS + 20:
            raise ValueError("RETRAINING_DATASET_TOO_SMALL")

        # Stage 2: checksum.
        dataset_checksum = _checksum_candles(sorted_candles)
        stages.append("CHECKSUM_COMPUTED")

        # Stage 3 + 4: feature generation (past-only) + label generation (forward-looking, by
        # design - see module docstring).
        rows = _build_feature_label_rows(sorted_candles, symbol, timeframe)
        stages.append("FEATURES_GENERATED")
        stages.append("LABELS_GENERATED")

        # Stage 5: time-series split with purge/embargo.
        interval_hours = max(1, int(_interval_hours(sorted_candles)))
        folds = self._fold_runner.generate_folds(
            session_id=session_id or uuid4(), start_time=sorted_candles[0].close_time,
            end_time=sorted_candles[-1].close_time, num_folds=1,
            purge_hours=interval_hours, embargo_hours=interval_hours,
        )
        fold = folds[0]
        train_rows = [r for r in rows if fold.train_start <= r.timestamp < fold.train_end]
        val_rows = [r for r in rows if fold.validation_start <= r.timestamp < fold.validation_end]
        test_rows = [r for r in rows if fold.test_start <= r.timestamp <= fold.test_end]
        stages.append("TIME_SERIES_SPLIT_WITH_PURGE_EMBARGO")
        if not train_rows or not val_rows or not test_rows:
            raise ValueError("RETRAINING_SPLIT_PRODUCED_AN_EMPTY_FOLD")

        # Stage 6: training (bounded gradient descent).
        coefficients, intercept = _fit_logistic_regression(train_rows, self._max_iterations, self._learning_rate)
        stages.append("MODEL_TRAINED")

        # Stage 7: validation.
        validation_accuracy = _accuracy(coefficients, intercept, val_rows)
        stages.append("VALIDATED")

        # Stage 8: calibration - identity (no Platt fit) in this baseline; documented as such,
        # not a claim of a calibrated model.
        calibration = None
        stages.append("CALIBRATED")

        # Stage 9: test.
        test_accuracy = _accuracy(coefficients, intercept, test_rows)
        train_accuracy = _accuracy(coefficients, intercept, train_rows)
        stages.append("TESTED")

        # Stage 10: artifact + registry publication - always RESEARCH_ONLY, never APPROVED.
        model_version = f"lr_{job_id.hex[:8]}"
        artifact: Dict[str, Any] = {
            "feature_names": FEATURE_NAMES, "coefficients": coefficients, "intercept": intercept,
            "calibration": calibration, "decision_threshold": 0.5,
        }
        entry_name = f"{strategy_name}_{symbol.replace('/', '')}_{timeframe.value}_lr"
        self._model_registry.register(RegistryEntry(
            name=entry_name, version=model_version, status=RegistryEntryStatus.RESEARCH_ONLY,
            artifact_location=f"inline://{job_id}",
            artifact_checksum=hashlib.sha256(json.dumps(artifact, sort_keys=True).encode("utf-8")).hexdigest(),
            code_commit=code_commit, configuration_hash=strategy_config_hash,
            compatible_symbols=[symbol], compatible_timeframes=[timeframe.value],
            dependencies={
                "dataset_checksum": dataset_checksum, "feature_version": FEATURE_VERSION,
                "label_version": LABEL_VERSION,
            },
            reason_codes=["RETRAINING_JOB_OUTPUT"],
        ))
        stages.append("ARTIFACT_PUBLISHED_RESEARCH_ONLY")

        # Stage 11: evidence review request - INSUFFICIENT, explicitly awaiting human review.
        # Never auto-promoted to any APPROVED status by this workflow.
        evidence_key = EvidenceKey(
            strategy_name=strategy_name, strategy_version=strategy_version, symbol=symbol,
            timeframe=timeframe.value, model_type=ModelType.LOGISTIC_REGRESSION.value, model_version=model_version,
            feature_version=FEATURE_VERSION, label_version=LABEL_VERSION, dataset_checksum=dataset_checksum,
            gate_version=gate_version, config_hash=strategy_config_hash, code_commit=code_commit,
        )
        self._evidence_store.register(EvidenceRecord(
            key=evidence_key, status=EvidenceStatus.INSUFFICIENT, generated_at=datetime.now(timezone.utc),
            total_oos_trades=len(test_rows),
            reasons=["RETRAINED_MODEL_AWAITING_HUMAN_REVIEW", f"test_accuracy={test_accuracy:.4f}"],
        ))
        stages.append("EVIDENCE_REVIEW_REQUESTED")

        return RetrainingJobResult(
            job_id=job_id, dataset_checksum=dataset_checksum, symbol=symbol, timeframe=timeframe.value,
            feature_version=FEATURE_VERSION, label_version=LABEL_VERSION, model_type=ModelType.LOGISTIC_REGRESSION,
            model_version=model_version, stages_completed=stages, train_sample_count=len(train_rows),
            validation_sample_count=len(val_rows), test_sample_count=len(test_rows),
            train_accuracy=train_accuracy, validation_accuracy=validation_accuracy, test_accuracy=test_accuracy,
            registry_status=RegistryEntryStatus.RESEARCH_ONLY, evidence_key=evidence_key,
            reason_codes=["RETRAINED_MODEL_REQUIRES_HUMAN_REVIEW_BEFORE_APPROVAL"],
        )


def rollback_model_version(
    registry: ArtifactRegistry, name: str, version: str, actor: str, reason: str,
) -> RegistryEntry:
    """The only rollback path this task provides: disable a specific (name, version). Restoring
    an older version to active use is a separate, ordinary registry transition on that older
    entry - this function only ever disables, it never re-enables anything, so it can't be
    used to promote a model."""
    if not actor:
        raise ValueError("Model rollback requires a named human actor.")
    return registry.transition_status(
        name, version, RegistryEntryStatus.DISABLED, reason_codes=[f"ROLLBACK_BY:{actor}", reason],
    )


def _checksum_candles(candles: List[Candle]) -> str:
    hasher = hashlib.sha256()
    for c in candles:
        hasher.update(f"{c.close_time.isoformat()}:{c.close_price}".encode("utf-8"))
    return hasher.hexdigest()


def _interval_hours(candles: List[Candle]) -> float:
    if len(candles) < 2:
        return 1.0
    return (candles[1].close_time - candles[0].close_time).total_seconds() / 3600.0


def _build_feature_label_rows(candles: List[Candle], symbol: str, timeframe: Timeframe) -> List[_Row]:
    rows: List[_Row] = []
    for idx in range(MIN_LOOKBACK_BARS, len(candles) - 1):  # -1: need a next bar for the label
        window_start = max(0, idx + 1 - FEATURE_LOOKBACK_WINDOW)
        buffer = candles[window_start: idx + 1]
        current = candles[idx]
        next_candle = candles[idx + 1]

        feature_req = FeatureComputationRequest(
            exchange="binance", symbol=symbol, timeframe=timeframe,
            feature_set="standard_v1", as_of_time=current.close_time,
        )
        snapshot = feature_pipeline.compute(feature_req, buffer)
        raw_values = [snapshot.values.get(name) for name in FEATURE_NAMES]
        if any(v is None for v in raw_values):
            continue  # honest skip - never impute a missing feature for training either
        features = [float(v) for v in raw_values]  # type: ignore[arg-type]
        label = 1 if next_candle.close_price > current.close_price else 0
        rows.append(_Row(timestamp=current.close_time, features=features, label=label))
    return rows


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _fit_logistic_regression(
    rows: List[_Row], max_iterations: int, learning_rate: float,
) -> "tuple[List[float], float]":
    n_features = len(rows[0].features)
    coefficients = [0.0] * n_features
    intercept = 0.0
    n = len(rows)

    for _ in range(max_iterations):
        grad_coef = [0.0] * n_features
        grad_intercept = 0.0
        for row in rows:
            z = intercept + sum(c * f for c, f in zip(coefficients, row.features, strict=True))
            prediction = _sigmoid(z)
            error = prediction - row.label
            for j in range(n_features):
                grad_coef[j] += error * row.features[j]
            grad_intercept += error
        coefficients = [c - learning_rate * (g / n) for c, g in zip(coefficients, grad_coef, strict=True)]
        intercept -= learning_rate * (grad_intercept / n)

    return coefficients, intercept


def _accuracy(coefficients: List[float], intercept: float, rows: List[_Row]) -> float:
    if not rows:
        return 0.0
    correct = 0
    for row in rows:
        z = intercept + sum(c * f for c, f in zip(coefficients, row.features, strict=True))
        predicted_label = 1 if _sigmoid(z) > 0.5 else 0
        if predicted_label == row.label:
            correct += 1
    return correct / len(rows)
