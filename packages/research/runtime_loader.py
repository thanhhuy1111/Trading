"""Loads a trained, checksummed model artifact into the runtime
`packages.prediction.registry.model_registry` -- the SAME registry
`PredictionService.predict()` looks up, so a model loaded here is immediately usable by
the live recommendation pipeline (packages/recommendation/service.py) without any glue
code.

The hard safety rule enforced here, not just documented: `load_approved_model` refuses to
register anything unless `packages.recommendation.evidence_service.evidence_registry`
already has an `APPROVED` `StrategyEvidence` for the exact (strategy_name,
strategy_version) pair. This is what makes "Recommendation Service must not automatically
select an unapproved artifact" (implementation plan section 19) true in code: there is no
path from a freshly trained model to the runtime registry that skips this check.
"""

from decimal import Decimal
from typing import Optional

from packages.prediction.direction_model import LogisticRegressionDirectionModel, LogisticRegressionWeights
from packages.prediction.meta_label_model import ThresholdMetaLabelModel
from packages.prediction.registry import ModelArtifact, ModelRegistry, model_registry
from packages.prediction.return_model import LinearRegressionWeights, LinearReturnModel
from packages.prediction.volatility_model import RealizedVolatilityModel
from packages.recommendation.evidence_service import EvidenceRegistry, evidence_registry
from packages.recommendation.models import EvidenceStatus
from packages.research.artifacts import ArtifactStore, artifact_store
from packages.research.models import ModelArtifactRecord


class ModelNotApprovedError(Exception):
    """Raised when a caller tries to load a model whose strategy/version has no APPROVED
    StrategyEvidence -- this is a refusal, not a bug, and callers should treat it as such."""


def load_approved_model(
    model_id: str,
    strategy_name: str,
    strategy_version: str,
    symbol: str,
    timeframe: str,
    horizon_minutes: int,
    store: ArtifactStore = artifact_store,
    prediction_registry: ModelRegistry = model_registry,
    evidence_reg: EvidenceRegistry = evidence_registry,
) -> ModelArtifact:
    evidence = evidence_reg.lookup(strategy_name, strategy_version)
    if evidence is None or evidence.status != EvidenceStatus.APPROVED:
        status = evidence.status.value if evidence else "NO_EVIDENCE_RECORDED"
        raise ModelNotApprovedError(
            f"Refusing to load model {model_id} into the runtime registry: strategy "
            f"'{strategy_name}' v{strategy_version} evidence status is {status}, not APPROVED"
        )

    record = store.load_metadata("models", model_id, ModelArtifactRecord)
    direction_weights = store.load_weights_json(f"{model_id}_direction", LogisticRegressionWeights)
    return_weights = store.load_weights_json(f"{model_id}_return", LinearRegressionWeights)

    artifact = ModelArtifact(
        symbol=symbol,
        timeframe=timeframe,
        horizon_minutes=horizon_minutes,
        model_version=record.model_version,
        feature_version=record.feature_version,
        direction_model=LogisticRegressionDirectionModel(direction_weights),
        return_model=LinearReturnModel(return_weights),
        volatility_model=RealizedVolatilityModel(),
        meta_label_model=ThresholdMetaLabelModel(),
        calibration_score=_extract_calibration_score(evidence.calibration_metrics),
        dataset_checksum=record.dataset_checksum,
        trained_at=record.created_at,
    )
    prediction_registry.register(artifact)
    return artifact


def _extract_calibration_score(calibration_metrics: Optional[str]) -> Optional[Decimal]:
    """`calibration_metrics` is the "k=v,k=v" string packages.research.evidence_publisher
    writes; pulls calibration_score back out of it. Returns None if absent/unparseable
    rather than fabricating a score.
    """
    if not calibration_metrics:
        return None
    for part in calibration_metrics.split(","):
        if part.startswith("calibration_score="):
            try:
                return Decimal(part.split("=", 1)[1])
            except Exception:  # noqa: BLE001 - malformed metadata should not crash loading
                return None
    return None


def unload_model(
    symbol: str, timeframe: str, horizon_minutes: int, prediction_registry: ModelRegistry = model_registry
) -> None:
    prediction_registry.unregister(symbol, timeframe, horizon_minutes)
