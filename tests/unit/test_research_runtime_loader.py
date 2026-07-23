"""Unit tests for packages/research/runtime_loader.py -- the runtime safety gate."""

import shutil
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from packages.prediction.direction_model import LogisticRegressionWeights
from packages.prediction.registry import ModelRegistry
from packages.prediction.return_model import LinearRegressionWeights
from packages.recommendation.evidence_service import EvidenceRegistry
from packages.recommendation.models import EvidenceStatus, StrategyEvidence
from packages.research.artifacts import ArtifactStore
from packages.research.models import ModelArtifactRecord
from packages.research.runtime_loader import (
    ModelNotApprovedError,
    _extract_calibration_score,
    load_approved_model,
    unload_model,
)

NOW = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def tmp_store():
    tmp_dir = tempfile.mkdtemp(prefix="runtime_loader_test_")
    yield ArtifactStore(root=tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _save_fake_model_artifact(store: ArtifactStore, model_id: str) -> None:
    record = ModelArtifactRecord(
        model_id=model_id, model_type="logistic_regression", model_version="logreg_v1",
        feature_version="standard_v1", dataset_checksum="abc123", label_version="triple_barrier_v1",
        hyperparameters={"max_iter": 500}, random_seed=42, train_period="p1", validation_period="p2",
        test_period="p3", code_commit="deadbeef", artifact_path=f"models/{model_id}",
        artifact_checksum="xyz", config_hash="cfg-hash", created_at=NOW,
    )
    store.save_metadata("models", model_id, record)
    direction_weights = LogisticRegressionWeights(
        model_version="logreg_v1", feature_names=["ema_20_slope"], up_coefficients=[1.0], up_intercept=0.0,
        down_coefficients=[-1.0], down_intercept=0.0,
    )
    return_weights = LinearRegressionWeights(
        model_version="logreg_v1", feature_names=["ema_20_slope"], coefficients=[10.0], intercept=1.0
    )
    store.save_weights_json(f"{model_id}_direction", direction_weights)
    store.save_weights_json(f"{model_id}_return", return_weights)


def _approved_evidence(calibration_metrics="method=platt,calibration_score=0.8500") -> StrategyEvidence:
    return StrategyEvidence(
        strategy_name="multi_agent_consensus_pipeline", strategy_version="1.0.0", model_version="logreg_v1",
        feature_version="standard_v1", config_hash="cfg-hash", status=EvidenceStatus.APPROVED,
        calibration_metrics=calibration_metrics, created_at=NOW,
    )


def test_load_approved_model_refuses_when_no_evidence(tmp_store):
    _save_fake_model_artifact(tmp_store, "model-1")
    prediction_registry = ModelRegistry()
    evidence_registry = EvidenceRegistry()  # empty

    with pytest.raises(ModelNotApprovedError):
        load_approved_model(
            "model-1", "multi_agent_consensus_pipeline", "1.0.0", "BTCUSDT", "1h", 60,
            store=tmp_store, prediction_registry=prediction_registry, evidence_reg=evidence_registry,
        )
    assert len(prediction_registry) == 0


def test_load_approved_model_refuses_when_evidence_not_approved(tmp_store):
    _save_fake_model_artifact(tmp_store, "model-1")
    prediction_registry = ModelRegistry()
    evidence_registry = EvidenceRegistry()
    research_only = _approved_evidence().model_copy(update={"status": EvidenceStatus.RESEARCH_ONLY})
    evidence_registry.register(research_only)

    with pytest.raises(ModelNotApprovedError):
        load_approved_model(
            "model-1", "multi_agent_consensus_pipeline", "1.0.0", "BTCUSDT", "1h", 60,
            store=tmp_store, prediction_registry=prediction_registry, evidence_reg=evidence_registry,
        )
    assert len(prediction_registry) == 0


def test_load_approved_model_succeeds_when_evidence_approved(tmp_store):
    _save_fake_model_artifact(tmp_store, "model-1")
    prediction_registry = ModelRegistry()
    evidence_registry = EvidenceRegistry()
    evidence_registry.register(_approved_evidence())

    artifact = load_approved_model(
        "model-1", "multi_agent_consensus_pipeline", "1.0.0", "BTCUSDT", "1h", 60,
        store=tmp_store, prediction_registry=prediction_registry, evidence_reg=evidence_registry,
    )

    assert artifact.symbol == "BTCUSDT"
    assert artifact.model_version == "logreg_v1"
    assert artifact.calibration_score == Decimal("0.8500")
    looked_up = prediction_registry.lookup("BTCUSDT", "1h", 60)
    assert looked_up is artifact


def test_load_approved_model_raises_for_missing_artifact_files(tmp_store):
    # No model artifact saved at all.
    evidence_registry = EvidenceRegistry()
    evidence_registry.register(_approved_evidence())
    from packages.research.exceptions import ArtifactNotFoundError

    with pytest.raises(ArtifactNotFoundError):
        load_approved_model(
            "does-not-exist", "multi_agent_consensus_pipeline", "1.0.0", "BTCUSDT", "1h", 60,
            store=tmp_store, prediction_registry=ModelRegistry(), evidence_reg=evidence_registry,
        )


def test_extract_calibration_score_parses_value():
    assert _extract_calibration_score("method=platt,calibration_score=0.9000") == Decimal("0.9000")


def test_extract_calibration_score_none_when_absent():
    assert _extract_calibration_score("method=platt,brier=0.15") is None


def test_extract_calibration_score_none_when_input_none():
    assert _extract_calibration_score(None) is None


def test_unload_model_removes_registration(tmp_store):
    prediction_registry = ModelRegistry()
    evidence_registry = EvidenceRegistry()
    evidence_registry.register(_approved_evidence())
    _save_fake_model_artifact(tmp_store, "model-1")

    load_approved_model(
        "model-1", "multi_agent_consensus_pipeline", "1.0.0", "BTCUSDT", "1h", 60,
        store=tmp_store, prediction_registry=prediction_registry, evidence_reg=evidence_registry,
    )
    assert prediction_registry.lookup("BTCUSDT", "1h", 60) is not None

    unload_model("BTCUSDT", "1h", 60, prediction_registry=prediction_registry)
    assert prediction_registry.lookup("BTCUSDT", "1h", 60) is None
