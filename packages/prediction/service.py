"""Prediction Service: the single place a ModelPrediction is produced.

If no calibrated artifact is registered for (symbol, timeframe, horizon_minutes), this
returns an honestly UNAVAILABLE prediction -- it never falls back to a heuristic agent
confidence score or any other stand-in for a calibrated probability.
"""

from datetime import datetime, timezone
from decimal import Decimal

from packages.features.models import FeatureSnapshot
from packages.prediction.feature_adapter import to_feature_vector
from packages.prediction.models import CalibrationStatus, ModelPrediction
from packages.prediction.registry import ModelRegistry, model_registry


class PredictionService:
    def __init__(self, registry: ModelRegistry = model_registry) -> None:
        self._registry = registry

    def predict(
        self,
        symbol: str,
        timeframe: str,
        horizon_minutes: int,
        feature_snapshot: FeatureSnapshot,
    ) -> ModelPrediction:
        now = datetime.now(timezone.utc)
        snapshot_id = str(feature_snapshot.snapshot_id)

        artifact = self._registry.lookup(symbol, timeframe, horizon_minutes)
        if artifact is None:
            return ModelPrediction(
                symbol=symbol,
                timeframe=timeframe,
                horizon_minutes=horizon_minutes,
                calibration_status=CalibrationStatus.UNAVAILABLE,
                model_version="none",
                feature_snapshot_id=snapshot_id,
                generated_at=now,
                meta_label_accepted=False,
                reason_codes=["NO_TRAINED_MODEL_ARTIFACT"],
            )

        features = to_feature_vector(feature_snapshot)
        direction = artifact.direction_model.predict_proba(features)
        expected_return_bps = Decimal(str(artifact.return_model.predict_expected_return_bps(features)))
        expected_volatility_bps = artifact.volatility_model.predict_expected_volatility_bps(feature_snapshot)

        probability_profit = Decimal(str(direction.probability_up))
        meta_decision = artifact.meta_label_model.evaluate(
            probability_profit=probability_profit,
            expected_net_return_bps=expected_return_bps,
            expected_volatility_bps=expected_volatility_bps or Decimal("0"),
        )

        calibration_status = (
            CalibrationStatus.CALIBRATED if artifact.calibration_score is not None else CalibrationStatus.UNCALIBRATED
        )
        reason_codes = list(meta_decision.reason_codes)
        if calibration_status != CalibrationStatus.CALIBRATED:
            reason_codes.append("MODEL_NOT_CALIBRATION_EVALUATED")

        return ModelPrediction(
            symbol=symbol,
            timeframe=timeframe,
            horizon_minutes=horizon_minutes,
            probability_up=Decimal(str(direction.probability_up)),
            probability_down=Decimal(str(direction.probability_down)),
            probability_flat=Decimal(str(direction.probability_flat)),
            probability_profit=probability_profit,
            expected_return_bps=expected_return_bps,
            expected_volatility_bps=expected_volatility_bps,
            calibration_status=calibration_status,
            calibration_score=artifact.calibration_score,
            model_version=artifact.model_version,
            feature_snapshot_id=snapshot_id,
            generated_at=now,
            meta_label_accepted=meta_decision.accept,
            reason_codes=reason_codes,
        )


prediction_service = PredictionService()
