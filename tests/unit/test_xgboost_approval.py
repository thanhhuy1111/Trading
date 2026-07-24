"""Offline acceptance tests for Phase 4D approval and atomic artifacts."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

from packages.common.immutable import FrozenMapping
from packages.domain.enums import RegistryEntryStatus
from packages.market_data.models import Candle, DataQualityStatus, Timeframe
from packages.registries.models import RegistryEntry
from packages.registries.registry import ArtifactRegistry, DuplicateRegistryEntryError
from packages.retraining.xgboost_approval import (
    ApprovalDecisionStatus,
    XGBoostApprovalGate,
    XGBoostApprovalService,
)
from packages.retraining.xgboost_artifacts import (
    ARTIFACT_FILES,
    XGBoostArtifactWriter,
    verify_artifact_directory,
    verify_artifact_receipt,
)
from packages.retraining.xgboost_contracts import DatasetMode
from packages.retraining.xgboost_dataset import xgboost_dataset_builder
from packages.retraining.xgboost_training import (
    TrainingStatus,
    XGBoostTrainingResult,
    xgboost_walk_forward_trainer,
)

BASE_TIME = datetime(2020, 1, 1, tzinfo=timezone.utc)
EVALUATED_AT = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
H4 = timedelta(hours=4)


def _candles(returns: Sequence[float]) -> list[Candle]:
    prices = [50000.0]
    for value in returns:
        prices.append(prices[-1] * float(np.exp(value)))
    candles: list[Candle] = []
    for index, value in enumerate(returns):
        open_time = BASE_TIME + index * H4
        close_time = open_time + H4 - timedelta(milliseconds=1)
        open_price = Decimal(str(prices[index]))
        close_price = Decimal(str(prices[index + 1]))
        candles.append(
            Candle(
                exchange="binance",
                symbol="BTC/USDT",
                exchange_timestamp=close_time,
                received_timestamp=close_time + timedelta(seconds=1),
                source="offline_approval_fixture",
                data_quality_status=DataQualityStatus.HEALTHY,
                timeframe=Timeframe.H4,
                open_time=open_time,
                close_time=close_time,
                open_price=open_price,
                high_price=max(open_price, close_price) * Decimal("1.001"),
                low_price=min(open_price, close_price) * Decimal("0.999"),
                close_price=close_price,
                volume=Decimal(str(1000 + abs(value) * 100000 + index % 7)),
                is_closed=True,
            )
        )
    return candles


def _dataset_and_training(*, strong: bool):
    count = 930
    if strong:
        block = [0.006] * 8 + [0.0] * 8 + [-0.006] * 8
        returns = [block[index % len(block)] for index in range(count)]
    else:
        returns = np.random.default_rng(123).normal(0.0, 0.004, count).tolist()
    dataset = xgboost_dataset_builder.build(
        _candles(returns),
        mode=DatasetMode.PRICE_ONLY,
        threshold_k=Decimal("0.50"),
    )
    training = xgboost_walk_forward_trainer.train(dataset)
    assert training.status == TrainingStatus.VALID
    return dataset, training


@pytest.fixture(scope="module")
def strong_evidence():
    return _dataset_and_training(strong=True)


@pytest.fixture(scope="module")
def weak_evidence():
    return _dataset_and_training(strong=False)


def _publish(
    tmp_path: Path,
    dataset: object,
    training: XGBoostTrainingResult,
    *,
    version: str,
):
    registry = ArtifactRegistry("xgboost_test")
    service = XGBoostApprovalService(registry, tmp_path)
    result = service.evaluate_and_publish(
        model_name="xgb_btcusdt_4h",
        model_version=version,
        dataset=dataset,  # type: ignore[arg-type]
        training=training,
        evaluated_at=EVALUATED_AT,
        code_commit="test-commit",
    )
    return registry, service, result


def test_strong_fixture_passes_gate_and_writes_five_atomic_files(
    tmp_path: Path,
    strong_evidence: tuple[object, XGBoostTrainingResult],
) -> None:
    dataset, training = strong_evidence
    registry, service, result = _publish(
        tmp_path,
        dataset,
        training,
        version="1.0.0",
    )

    assert result.decision.status == ApprovalDecisionStatus.APPROVED
    assert result.decision.reason_codes == ()
    assert result.registry_entry.status == RegistryEntryStatus.APPROVED
    assert result.manifest is not None
    assert result.manifest.calibrated_roundtrip_max_abs_error <= 1e-9
    artifact_path = Path(result.manifest.artifact_path)
    assert {path.name for path in artifact_path.iterdir()} == set(ARTIFACT_FILES)
    verified = verify_artifact_directory(artifact_path)
    assert verified.valid
    receipt_verified = verify_artifact_receipt(
        artifact_path,
        approval_checksum=result.receipt.approval_checksum or "",
        file_checksums=result.receipt.file_checksums,
        expected_status="APPROVED",
    )
    assert receipt_verified.valid
    assert service.get_receipt("xgb_btcusdt_4h", "1.0.0") == result.receipt
    assert registry.get("xgb_btcusdt_4h", "1.0.0") == result.registry_entry


def test_weak_noise_fixture_is_honestly_rejected_but_auditable(
    tmp_path: Path,
    weak_evidence: tuple[object, XGBoostTrainingResult],
) -> None:
    dataset, training = weak_evidence
    _, _, result = _publish(tmp_path, dataset, training, version="weak-1")

    assert result.decision.status == ApprovalDecisionStatus.REJECTED
    assert result.decision.reason_codes
    assert result.registry_entry.status == RegistryEntryStatus.REJECTED
    assert result.manifest is not None
    assert set(Path(result.manifest.artifact_path).iterdir()) == {
        Path(result.manifest.artifact_path) / filename for filename in ARTIFACT_FILES
    }
    verified = verify_artifact_directory(Path(result.manifest.artifact_path))
    assert verified.valid
    assert verified.approval is not None
    assert verified.approval["status"] == "REJECTED"


def test_gate_recomputes_metrics_schema_probabilities_and_calibration(
    strong_evidence: tuple[object, XGBoostTrainingResult],
) -> None:
    dataset, training = strong_evidence
    assert training.report is not None
    first_fold = training.report.folds[0]
    evaluations = dict(first_fold.evaluations)
    xgboost_evaluation = evaluations["xgboost"]
    evaluations["xgboost"] = xgboost_evaluation.model_copy(
        update={
            "metrics": xgboost_evaluation.metrics.model_copy(
                update={"accuracy": 0.123}
            )
        }
    )
    forged_fold = first_fold.model_copy(
        update={"evaluations": FrozenMapping(evaluations)}
    )
    forged_report = training.report.model_copy(
        update={"folds": (forged_fold, *training.report.folds[1:])}
    )
    forged_training = training.model_copy(update={"report": forged_report})
    metric_decision = XGBoostApprovalGate().evaluate(dataset, forged_training)
    assert metric_decision.status == ApprovalDecisionStatus.REJECTED
    assert "FOLD_1_XGBOOST_METRICS_MISMATCH" in metric_decision.reason_codes

    boundary_forgery = xgboost_evaluation.model_copy(
        update={
            "metrics": xgboost_evaluation.metrics.model_copy(
                update={
                    "balanced_accuracy": (
                        xgboost_evaluation.metrics.balanced_accuracy + 5e-13
                    )
                }
            )
        }
    )
    boundary_evaluations = dict(first_fold.evaluations)
    boundary_evaluations["xgboost"] = boundary_forgery
    boundary_fold = first_fold.model_copy(
        update={"evaluations": FrozenMapping(boundary_evaluations)}
    )
    boundary_report = training.report.model_copy(
        update={"folds": (boundary_fold, *training.report.folds[1:])}
    )
    boundary_decision = XGBoostApprovalGate().evaluate(
        dataset,
        training.model_copy(update={"report": boundary_report}),
    )
    assert boundary_decision.status == ApprovalDecisionStatus.REJECTED
    assert "TRAINING_EVIDENCE_MISMATCH" in boundary_decision.reason_codes

    wrong_schema_report = training.report.model_copy(
        update={"feature_schema_hash": "0" * 64}
    )
    wrong_schema = training.model_copy(update={"report": wrong_schema_report})
    schema_decision = XGBoostApprovalGate().evaluate(dataset, wrong_schema)
    assert "FEATURE_SCHEMA_MISMATCH" in schema_decision.reason_codes

    bad_evaluations = dict(first_fold.evaluations)
    bad_evaluations["xgboost"] = xgboost_evaluation.model_copy(
        update={"probabilities": ((0.2, 0.2, 0.2),) * first_fold.test_samples}
    )
    bad_fold = first_fold.model_copy(
        update={"evaluations": FrozenMapping(bad_evaluations)}
    )
    bad_report = training.report.model_copy(
        update={"folds": (bad_fold, *training.report.folds[1:])}
    )
    probability_decision = XGBoostApprovalGate().evaluate(
        dataset,
        training.model_copy(update={"report": bad_report}),
    )
    assert probability_decision.status == ApprovalDecisionStatus.REJECTED
    assert "FOLD_1_XGBOOST_PROBABILITY_INVALID" in probability_decision.reason_codes

    bad_calibration = first_fold.model_copy(
        update={"temperature": first_fold.temperature + 1.0}  # type: ignore[operator]
    )
    calibration_report = training.report.model_copy(
        update={"folds": (bad_calibration, *training.report.folds[1:])}
    )
    calibration_decision = XGBoostApprovalGate().evaluate(
        dataset,
        training.model_copy(update={"report": calibration_report}),
    )
    assert "FOLD_1_CALIBRATION_MISMATCH" in calibration_decision.reason_codes

    from xgboost import XGBClassifier

    altered_model = XGBClassifier(**dict(training.report.hyperparameters))
    altered_model.fit(
        np.random.default_rng(8).normal(size=(300, len(dataset.samples[0].feature_names))),
        np.tile(np.arange(3), 100),
    )
    altered_decision = XGBoostApprovalGate().evaluate(
        dataset,
        training.model_copy(update={"final_model": altered_model}),
    )
    assert altered_decision.status == ApprovalDecisionStatus.REJECTED
    assert "FINAL_MODEL_EVIDENCE_MISMATCH" in altered_decision.reason_codes


def test_checksum_missing_schema_and_forged_approval_fail_verification(
    tmp_path: Path,
    strong_evidence: tuple[object, XGBoostTrainingResult],
) -> None:
    dataset, training = strong_evidence
    _, _, result = _publish(tmp_path, dataset, training, version="tamper-1")
    assert result.manifest is not None
    artifact_path = Path(result.manifest.artifact_path)

    evaluation_path = artifact_path / "evaluation.json"
    evaluation_path.write_text("{}", encoding="utf-8")
    tampered = verify_artifact_directory(artifact_path)
    assert not tampered.valid
    assert tampered.reason_codes == ("ARTIFACT_CHECKSUM_MISMATCH:evaluation.json",)

    _, _, missing_result = _publish(
        tmp_path,
        dataset,
        training,
        version="missing-1",
    )
    assert missing_result.manifest is not None
    missing_path = Path(missing_result.manifest.artifact_path)
    (missing_path / "metadata.json").unlink()
    missing = verify_artifact_directory(missing_path)
    assert not missing.valid
    assert "ARTIFACT_FILE_MISSING:metadata.json" in missing.reason_codes

    _, _, forged_result = _publish(
        tmp_path,
        dataset,
        training,
        version="forged-1",
    )
    assert forged_result.manifest is not None
    forged_path = Path(forged_result.manifest.artifact_path)
    approval_path = forged_path / "approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["status"] = "REJECTED"
    approval_path.write_text(
        json.dumps(approval, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    forged = verify_artifact_receipt(
        forged_path,
        approval_checksum=forged_result.receipt.approval_checksum or "",
        file_checksums=forged_result.receipt.file_checksums,
        expected_status="APPROVED",
    )
    assert not forged.valid
    assert forged.reason_codes == ("APPROVAL_RECEIPT_CHECKSUM_MISMATCH",)


def test_duplicate_direct_injection_and_rejected_resurrection_are_blocked(
    tmp_path: Path,
    strong_evidence: tuple[object, XGBoostTrainingResult],
    weak_evidence: tuple[object, XGBoostTrainingResult],
) -> None:
    strong_dataset, strong_training = strong_evidence
    registry = ArtifactRegistry("xgboost_test")
    registry.register(
        RegistryEntry(
            name="direct",
            version="1",
            status=RegistryEntryStatus.APPROVED,
        )
    )
    service = XGBoostApprovalService(registry, tmp_path)
    with pytest.raises(ValueError, match="MODEL_VERSION_EXISTS"):
        service.evaluate_and_publish(
            model_name="direct",
            model_version="1",
            dataset=strong_dataset,  # type: ignore[arg-type]
            training=strong_training,
            evaluated_at=EVALUATED_AT,
            code_commit="test",
        )
    assert service.get_receipt("direct", "1") is None

    weak_dataset, weak_training = weak_evidence
    rejected = service.evaluate_and_publish(
        model_name="weak",
        model_version="1",
        dataset=weak_dataset,  # type: ignore[arg-type]
        training=weak_training,
        evaluated_at=EVALUATED_AT,
        code_commit="test",
    )
    assert rejected.registry_entry.status == RegistryEntryStatus.REJECTED
    with pytest.raises(DuplicateRegistryEntryError):
        registry.register(
            RegistryEntry(
                name="weak",
                version="1",
                status=RegistryEntryStatus.APPROVED,
            )
        )
    assert registry.get("weak", "1").status == RegistryEntryStatus.REJECTED  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="MODEL_VERSION_EXISTS"):
        service.evaluate_and_publish(
            model_name="weak",
            model_version="1",
            dataset=strong_dataset,  # type: ignore[arg-type]
            training=strong_training,
            evaluated_at=EVALUATED_AT,
            code_commit="test",
        )


def test_cross_file_schema_tamper_path_traversal_and_atomic_cleanup(
    tmp_path: Path,
    strong_evidence: tuple[object, XGBoostTrainingResult],
) -> None:
    dataset, training = strong_evidence
    fresh_root = tmp_path / "fresh" / "nested" / "artifact-root"
    fresh_writer = XGBoostArtifactWriter(fresh_root)
    assert fresh_root.is_dir()
    assert fresh_writer is not None
    registry, service, result = _publish(
        tmp_path,
        dataset,
        training,
        version="schema-1",
    )
    assert result.manifest is not None
    artifact_path = Path(result.manifest.artifact_path)
    schema_path = artifact_path / "feature_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["feature_names"] = ["made_up_feature"]
    schema_path.write_text(
        json.dumps(schema, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    approval_path = artifact_path / "approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["file_checksums"]["feature_schema.json"] = hashlib.sha256(
        schema_path.read_bytes()
    ).hexdigest()
    approval_path.write_text(
        json.dumps(approval, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    cross_file = verify_artifact_directory(artifact_path)
    assert not cross_file.valid
    assert cross_file.reason_codes == ("ARTIFACT_FEATURE_SCHEMA_MISMATCH",)

    with pytest.raises(ValueError, match="ARTIFACT_ID_INVALID"):
        service.evaluate_and_publish(
            model_name="../escape",
            model_version="1",
            dataset=dataset,  # type: ignore[arg-type]
            training=training,
            evaluated_at=EVALUATED_AT,
            code_commit="test",
        )
    assert registry.get("../escape", "1") is None

    class SaveFailureModel:
        def predict_proba(self, values: object) -> object:
            return training.final_model.predict_proba(values)

        def save_model(self, path: object) -> None:
            raise OSError("disk failure")

    failed_training = training.model_copy(
        update={"final_model": SaveFailureModel()}
    )
    rejected = service.evaluate_and_publish(
        model_name="untrusted",
        model_version="1",
        dataset=dataset,  # type: ignore[arg-type]
        training=failed_training,
        evaluated_at=EVALUATED_AT,
        code_commit="test",
    )
    assert rejected.decision.status == ApprovalDecisionStatus.REJECTED
    assert "FINAL_MODEL_EVIDENCE_MISMATCH" in rejected.decision.reason_codes
    assert rejected.registry_entry.status == RegistryEntryStatus.REJECTED
    assert rejected.manifest is not None

    with pytest.raises(OSError, match="disk failure"):
        XGBoostArtifactWriter(tmp_path).write(
            model_name="atomic",
            model_version="1",
            dataset=dataset,  # type: ignore[arg-type]
            training=failed_training,
            approval_status="REJECTED",
            reason_codes=("FINAL_MODEL_EVIDENCE_MISMATCH",),
            gate_version="test-gate",
            evaluated_at=EVALUATED_AT,
            code_commit="test",
        )
    assert not (tmp_path / "atomic" / "1").exists()
    assert list((tmp_path / "atomic").glob(".1.staging-*")) == []

    artifact_root = tmp_path / "symlink-root"
    artifact_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (artifact_root / "redirected").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="ARTIFACT_PARENT_SYMLINK_FORBIDDEN"):
        XGBoostArtifactWriter(artifact_root).write(
            model_name="redirected",
            model_version="1",
            dataset=dataset,  # type: ignore[arg-type]
            training=training,
            approval_status="APPROVED",
            reason_codes=(),
            gate_version="test-gate",
            evaluated_at=EVALUATED_AT,
            code_commit="test",
        )
    assert list(outside.iterdir()) == []
