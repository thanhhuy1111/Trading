"""Offline acceptance tests for approved-only Phase 4E XGBoost runtime."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.common.immutable import FrozenMapping
from packages.domain.enums import RegistryEntryStatus
from packages.features.models import FeatureQualityStatus
from packages.registries.models import RegistryEntry
from packages.registries.registry import ArtifactRegistry
from packages.retraining.xgboost_approval import (
    ApprovalDecisionStatus,
    ApprovalPublicationResult,
    ApprovalReceipt,
    ApprovedModelReference,
    XGBoostApprovalService,
)
from packages.retraining.xgboost_artifacts import (
    ArtifactMetadata,
    XGBoostArtifactWriter,
)
from packages.retraining.xgboost_contracts import (
    PRICE_FEATURE_SET,
    PRICE_FEATURE_SET_VERSION,
    DatasetMode,
    XGBoostDatasetBuildResult,
)
from packages.retraining.xgboost_runtime import (
    ApprovedModelRepository,
    PredictionAvailability,
    XGBoostRuntime,
    XGBoostRuntimeFeatureSnapshot,
    XGBoostRuntimeRequest,
)
from packages.retraining.xgboost_training import (
    XGBoostTrainingResult,
    apply_temperature,
    validate_probabilities,
)
from tests.unit.test_xgboost_approval import EVALUATED_AT, _dataset_and_training


@pytest.fixture(scope="module")
def evidence() -> tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult]:
    return _dataset_and_training(strong=True)


@pytest.fixture(scope="module")
def weak_evidence() -> tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult]:
    return _dataset_and_training(strong=False)


def _publish(
    tmp_path: Path,
    evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
    *,
    version: str = "1.0.0",
) -> tuple[XGBoostApprovalService, ApprovalPublicationResult]:
    dataset, training = evidence
    service = XGBoostApprovalService(ArtifactRegistry("runtime"), tmp_path)
    result = service.evaluate_and_publish(
        model_name="xgb_btcusdt_4h",
        model_version=version,
        dataset=dataset,
        training=training,
        evaluated_at=EVALUATED_AT,
        code_commit="runtime-test",
    )
    assert result.decision.status == ApprovalDecisionStatus.APPROVED
    return service, result


def _snapshot(
    dataset: XGBoostDatasetBuildResult,
    **updates: object,
) -> XGBoostRuntimeFeatureSnapshot:
    sample = dataset.samples[-1]
    payload: dict[str, object] = {
        "feature_snapshot_id": "snapshot-fixed-001",
        "exchange_symbol": "BTCUSDT",
        "canonical_symbol": "BTC/USDT",
        "spot_exchange": "binance",
        "derivatives_exchange": None,
        "timeframe": "4h",
        "horizon_bars": 1,
        "dataset_mode": DatasetMode.PRICE_ONLY,
        "price_feature_set": PRICE_FEATURE_SET,
        "price_feature_set_version": PRICE_FEATURE_SET_VERSION,
        "feature_schema_hash": dataset.report.feature_schema_hash,
        "as_of_time": sample.as_of_time,
        "available_at": sample.feature_available_at,
        "quality_status": FeatureQualityStatus.VALID,
        "feature_names": sample.feature_names,
        "feature_values": sample.feature_values,
    }
    payload.update(updates)
    return XGBoostRuntimeFeatureSnapshot.model_validate(payload)


def _runtime(service: XGBoostApprovalService) -> XGBoostRuntime:
    return XGBoostRuntime(ApprovedModelRepository(service))


def test_exact_approved_artifact_predicts_calibrated_deterministic_output(
    tmp_path: Path,
    evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
) -> None:
    dataset, _ = evidence
    service, publication = _publish(tmp_path, evidence)
    request = XGBoostRuntimeRequest(
        model_name="xgb_btcusdt_4h",
        model_version="1.0.0",
        snapshot=_snapshot(dataset),
    )
    first = _runtime(service).predict(request)
    second = _runtime(service).predict(request)

    assert first == second
    assert first.status == PredictionAvailability.AVAILABLE
    assert first.reason_codes == ()
    assert first.probabilities is not None
    assert first.confidence == max(first.probabilities.values())
    assert abs(sum(first.probabilities.values()) - 1.0) <= 1e-6
    assert first.feature_snapshot_id == "snapshot-fixed-001"
    assert first.prediction_time == dataset.samples[-1].as_of_time
    assert publication.manifest is not None
    artifact_path = Path(publication.manifest.artifact_path)
    metadata = ArtifactMetadata.model_validate_json(
        (artifact_path / "metadata.json").read_bytes()
    )
    from xgboost import XGBClassifier

    model = XGBClassifier()
    model.load_model(artifact_path / "model.json")
    vector = [float(value) for value in dataset.samples[-1].feature_values.values()]
    raw = validate_probabilities(model.predict_proba([vector]).tolist())
    expected = apply_temperature(raw, metadata.temperature)[0]
    assert first.probabilities is not None
    assert tuple(first.probabilities.values()) == pytest.approx(expected)
    if metadata.temperature != 1.0:
        assert tuple(first.probabilities.values()) != pytest.approx(raw[0])


def test_no_receipt_direct_injection_and_ambiguous_versions_are_unavailable(
    tmp_path: Path,
    evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
) -> None:
    dataset, training = evidence
    registry = ArtifactRegistry("direct")
    registry.register(
        RegistryEntry(
            name="xgb_btcusdt_4h",
            version="forged",
            status=RegistryEntryStatus.APPROVED,
            compatible_symbols=("BTC/USDT",),
            compatible_timeframes=("4h",),
        )
    )
    injected_service = XGBoostApprovalService(registry, tmp_path / "injected")
    request = XGBoostRuntimeRequest(
        model_name="xgb_btcusdt_4h",
        snapshot=_snapshot(dataset),
    )
    injected = _runtime(injected_service).predict(request)
    assert injected.status == PredictionAvailability.UNAVAILABLE
    assert injected.reason_codes == ("NO_APPROVED_MODEL",)
    assert injected.confidence is None
    assert injected.prediction_time is None

    approved_registry = ArtifactRegistry("ambiguous")
    approved_service = XGBoostApprovalService(
        approved_registry,
        tmp_path / "ambiguous",
    )
    for version in ("1", "2"):
        result = approved_service.evaluate_and_publish(
            model_name="xgb_btcusdt_4h",
            model_version=version,
            dataset=dataset,
            training=training,
            evaluated_at=EVALUATED_AT,
            code_commit="runtime-test",
        )
        assert result.decision.status == ApprovalDecisionStatus.APPROVED
    ambiguous = _runtime(approved_service).predict(request)
    assert ambiguous.reason_codes == ("AMBIGUOUS_APPROVED_MODEL",)


def test_all_unsafe_registry_states_and_reference_mismatch_are_rejected(
    tmp_path: Path,
    evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
) -> None:
    dataset, _ = evidence
    snapshot = _snapshot(dataset)

    class StaticProvider:
        def list_approved_references(self) -> tuple[ApprovedModelReference, ...]:
            return ()

    for status in RegistryEntryStatus:
        registry = ArtifactRegistry(f"unsafe_{status.value}")
        entry = RegistryEntry(
            name="xgb_btcusdt_4h",
            version="1",
            status=status,
            artifact_location="/tmp/nonexistent",
            artifact_checksum="0" * 64,
            compatible_symbols=("BTC/USDT",),
            compatible_timeframes=("4h",),
        )
        registry.register(entry)
        service = XGBoostApprovalService(
            registry,
            tmp_path / status.value.lower(),
        )
        prediction = _runtime(service).predict(
            XGBoostRuntimeRequest(
                model_name="xgb_btcusdt_4h",
                model_version="1",
                snapshot=snapshot,
            )
        )
        assert prediction.reason_codes == ("NO_APPROVED_MODEL",)

    with pytest.raises(TypeError, match="APPROVAL_SERVICE_AUTHORITY_REQUIRED"):
        ApprovedModelRepository(StaticProvider())  # type: ignore[arg-type]


def test_direct_writer_plus_forged_receipt_provider_cannot_cross_authority_boundary(
    tmp_path: Path,
    weak_evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
) -> None:
    dataset, training = weak_evidence
    manifest = XGBoostArtifactWriter(tmp_path).write(
        model_name="weak_direct",
        model_version="1",
        dataset=dataset,
        training=training,
        approval_status="APPROVED",
        reason_codes=(),
        gate_version="forged-gate",
        evaluated_at=EVALUATED_AT,
        code_commit="forged",
    )
    entry = RegistryEntry(
        name="weak_direct",
        version="1",
        status=RegistryEntryStatus.APPROVED,
        artifact_location=manifest.artifact_path,
        artifact_checksum=manifest.approval_checksum,
        configuration_hash=dataset.report.feature_schema_hash,
        dependencies=FrozenMapping(
            {
                "dataset_checksum": dataset.report.dataset_checksum,
                "gate_version": "forged-gate",
            }
        ),
        compatible_symbols=("BTC/USDT",),
        compatible_timeframes=("4h",),
    )
    receipt = ApprovalReceipt(
        model_name="weak_direct",
        model_version="1",
        status=ApprovalDecisionStatus.APPROVED,
        gate_version="forged-gate",
        evaluated_at=EVALUATED_AT,
        dataset_checksum=dataset.report.dataset_checksum,
        feature_schema_hash=dataset.report.feature_schema_hash,
        artifact_path=manifest.artifact_path,
        approval_checksum=manifest.approval_checksum,
        file_checksums=manifest.file_checksums,
    )
    forged_reference = ApprovedModelReference(
        registry_entry=entry,
        receipt=receipt,
    )

    class ForgedProvider:
        def list_approved_references(self) -> tuple[ApprovedModelReference, ...]:
            return (forged_reference,)

    with pytest.raises(TypeError, match="APPROVAL_SERVICE_AUTHORITY_REQUIRED"):
        ApprovedModelRepository(ForgedProvider())  # type: ignore[arg-type]


def test_feature_status_missing_value_schema_and_contract_fail_closed(
    tmp_path: Path,
    evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
) -> None:
    dataset, _ = evidence
    service, _ = _publish(tmp_path, evidence)
    runtime = _runtime(service)

    for status, reason in (
        (FeatureQualityStatus.STALE, "FEATURE_DATA_STALE"),
        (FeatureQualityStatus.INVALID, "FEATURE_STATUS_INVALID"),
        (FeatureQualityStatus.DEGRADED, "FEATURE_STATUS_INVALID"),
    ):
        prediction = runtime.predict(
            XGBoostRuntimeRequest(
                model_name="xgb_btcusdt_4h",
                snapshot=_snapshot(dataset, quality_status=status),
            )
        )
        assert prediction.reason_codes == (reason,)

    values = dict(dataset.samples[-1].feature_values)
    values[dataset.samples[-1].feature_names[0]] = None
    missing = runtime.predict(
        XGBoostRuntimeRequest(
            model_name="xgb_btcusdt_4h",
            snapshot=_snapshot(dataset, feature_values=FrozenMapping(values)),
        )
    )
    assert missing.reason_codes == ("REQUIRED_FEATURE_MISSING",)

    wrong_schema = runtime.predict(
        XGBoostRuntimeRequest(
            model_name="xgb_btcusdt_4h",
            snapshot=_snapshot(dataset, feature_schema_hash="wrong"),
        )
    )
    assert wrong_schema.reason_codes == ("FEATURE_SCHEMA_MISMATCH",)

    wrong_set = runtime.predict(
        XGBoostRuntimeRequest(
            model_name="xgb_btcusdt_4h",
            snapshot=_snapshot(dataset, price_feature_set_version="9.9.9"),
        )
    )
    assert wrong_set.reason_codes == ("FEATURE_CONTRACT_MISMATCH",)


def test_invalid_timestamps_and_identity_are_rejected_by_input_contract(
    evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
) -> None:
    dataset, _ = evidence
    with pytest.raises(ValidationError):
        _snapshot(
            dataset,
            as_of_time=datetime(2026, 1, 1),
            available_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        _snapshot(dataset, timeframe="1h")
    with pytest.raises(ValidationError):
        _snapshot(dataset, horizon_bars=2)
    with pytest.raises(ValidationError):
        _snapshot(dataset, canonical_symbol="ETH/USDT")


def test_corruption_forged_approval_and_uncalibrated_artifact_fail_closed(
    tmp_path: Path,
    evidence: tuple[XGBoostDatasetBuildResult, XGBoostTrainingResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, _ = evidence
    service, result = _publish(tmp_path, evidence)
    assert result.manifest is not None
    artifact_path = Path(result.manifest.artifact_path)
    request = XGBoostRuntimeRequest(
        model_name="xgb_btcusdt_4h",
        model_version="1.0.0",
        snapshot=_snapshot(dataset),
    )

    model_path = artifact_path / "model.json"
    model_path.write_text("{}", encoding="utf-8")
    corrupted = _runtime(service).predict(request)
    assert corrupted.reason_codes == ("ARTIFACT_VERIFICATION_FAILED",)

    def unreadable(*args: object, **kwargs: object) -> object:
        raise OSError("simulated disappearing artifact")

    monkeypatch.setattr(
        "packages.retraining.xgboost_runtime.verify_artifact_receipt",
        unreadable,
    )
    unreadable_result = _runtime(service).predict(request)
    assert unreadable_result.reason_codes == ("ARTIFACT_VERIFICATION_FAILED",)
    monkeypatch.undo()

    service2, result2 = _publish(tmp_path / "forged", evidence, version="2")
    assert result2.manifest is not None
    artifact2 = Path(result2.manifest.artifact_path)
    metadata_path = artifact2 / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["temperature"] = None
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    approval_path = artifact2 / "approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["file_checksums"]["metadata.json"] = hashlib.sha256(
        metadata_path.read_bytes()
    ).hexdigest()
    approval_path.write_text(
        json.dumps(approval, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    uncalibrated = _runtime(service2).predict(
        XGBoostRuntimeRequest(
            model_name="xgb_btcusdt_4h",
            model_version="2",
            snapshot=_snapshot(dataset),
        )
    )
    assert uncalibrated.reason_codes == ("ARTIFACT_VERIFICATION_FAILED",)
