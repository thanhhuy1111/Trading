"""Unit tests for packages/prediction.

Central invariant under test: PredictionService.predict() NEVER fabricates a
probability. With an empty registry (the shipped default -- no trained artifact exists
anywhere in this repository) every prediction must come back UNAVAILABLE / unusable.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.features.models import FeatureLineage, FeatureSnapshot
from packages.market_data.models import Timeframe
from packages.prediction.calibration import (
    brier_score,
    calibration_score_from_ece,
    expected_calibration_error,
    reliability_buckets,
)
from packages.prediction.direction_model import LogisticRegressionDirectionModel, LogisticRegressionWeights
from packages.prediction.evaluation import DirectionModelEvaluation, hit_rate, log_loss
from packages.prediction.feature_adapter import realized_volatility_bps, to_feature_vector
from packages.prediction.meta_label_model import ThresholdMetaLabelModel
from packages.prediction.models import CalibrationStatus
from packages.prediction.registry import ModelArtifact, ModelRegistry
from packages.prediction.return_model import LinearRegressionWeights, LinearReturnModel
from packages.prediction.service import PredictionService
from packages.prediction.volatility_model import RealizedVolatilityModel

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _snapshot(**value_overrides) -> FeatureSnapshot:
    values = {
        "return_1p": Decimal("0.01"),
        "ema_20_slope": Decimal("0.002"),
        "adx_14": Decimal("28.0"),
        "rsi_14": Decimal("55.0"),
        "volatility_20": Decimal("0.015"),
        "relative_volume_20": Decimal("1.3"),
        "zscore_20": Decimal("0.4"),
        "donchian_breakout_20": Decimal("1.0"),
    }
    values.update(value_overrides)
    lineage = FeatureLineage(
        source_exchange="binance",
        source_symbol="BTCUSDT",
        source_timeframe="1h",
        candle_count_used=100,
        oldest_candle_timestamp=NOW,
        newest_candle_timestamp=NOW,
        calculator_versions={},
    )
    return FeatureSnapshot(
        snapshot_id=uuid4(),
        exchange="binance",
        symbol="BTCUSDT",
        timeframe=Timeframe.H1,
        feature_set="standard_v1",
        feature_set_version="1.0.0",
        event_time=NOW,
        as_of_time=NOW,
        computed_at=NOW,
        lookback_start=NOW,
        lookback_end=NOW,
        values=values,
        quality_status="VALID",
        quality_issues=[],
        source_data_version="v1",
        lineage=lineage,
        schema_version=1,
    )


# --------------------------------------------------------------------------------------
# feature_adapter
# --------------------------------------------------------------------------------------


def test_feature_vector_has_stable_shape_and_defaults_missing_to_zero():
    snapshot = _snapshot()
    vector = to_feature_vector(snapshot)
    assert vector["ema_20_slope"] == pytest.approx(0.002)
    assert vector["atr_14"] == 0.0  # not in values -> defaulted, not dropped


def test_realized_volatility_bps_reads_real_feature():
    snapshot = _snapshot(volatility_20=Decimal("0.02"))
    assert realized_volatility_bps(snapshot) == Decimal("200.0")


def test_realized_volatility_bps_none_when_feature_missing():
    snapshot = _snapshot(volatility_20=None)
    assert realized_volatility_bps(snapshot) is None


# --------------------------------------------------------------------------------------
# direction / return models (pure arithmetic inference)
# --------------------------------------------------------------------------------------


def test_logistic_direction_model_is_deterministic_and_bounded():
    weights = LogisticRegressionWeights(
        model_version="logreg_v1",
        feature_names=["ema_20_slope", "adx_14"],
        up_coefficients=[50.0, 0.02],
        up_intercept=-1.0,
        down_coefficients=[-50.0, 0.0],
        down_intercept=-1.5,
    )
    model = LogisticRegressionDirectionModel(weights)
    features = {"ema_20_slope": 0.002, "adx_14": 28.0}

    p1 = model.predict_proba(features)
    p2 = model.predict_proba(features)

    assert p1 == p2
    assert 0.0 <= p1.probability_up <= 1.0
    assert 0.0 <= p1.probability_down <= 1.0
    assert 0.0 <= p1.probability_flat <= 1.0
    assert p1.probability_up + p1.probability_down + p1.probability_flat == pytest.approx(1.0, abs=1e-6)


def test_linear_return_model_is_pure_arithmetic():
    weights = LinearRegressionWeights(
        model_version="linreg_v1", feature_names=["ema_20_slope"], coefficients=[1000.0], intercept=5.0
    )
    model = LinearReturnModel(weights)
    assert model.predict_expected_return_bps({"ema_20_slope": 0.01}) == pytest.approx(15.0)


def test_realized_volatility_model_wraps_feature_adapter():
    model = RealizedVolatilityModel()
    snapshot = _snapshot(volatility_20=Decimal("0.03"))
    assert model.predict_expected_volatility_bps(snapshot) == Decimal("300.0")


# --------------------------------------------------------------------------------------
# meta-label model
# --------------------------------------------------------------------------------------


def test_meta_label_rejects_non_positive_return():
    model = ThresholdMetaLabelModel()
    decision = model.evaluate(
        probability_profit=Decimal("0.6"),
        expected_net_return_bps=Decimal("-5.0"),
        expected_volatility_bps=Decimal("100.0"),
    )
    assert decision.accept is False
    assert "NON_POSITIVE_NET_RETURN" in decision.reason_codes


def test_meta_label_rejects_return_not_significant_vs_volatility():
    model = ThresholdMetaLabelModel(min_return_to_volatility_ratio=Decimal("0.5"))
    decision = model.evaluate(
        probability_profit=Decimal("0.6"),
        expected_net_return_bps=Decimal("10.0"),
        expected_volatility_bps=Decimal("100.0"),
    )
    assert decision.accept is False
    assert "RETURN_NOT_SIGNIFICANT_VS_VOLATILITY" in decision.reason_codes


def test_meta_label_accepts_healthy_edge():
    model = ThresholdMetaLabelModel()
    decision = model.evaluate(
        probability_profit=Decimal("0.6"),
        expected_net_return_bps=Decimal("50.0"),
        expected_volatility_bps=Decimal("100.0"),
    )
    assert decision.accept is True
    assert decision.reason_codes == []


# --------------------------------------------------------------------------------------
# calibration / evaluation
# --------------------------------------------------------------------------------------


def test_brier_score_perfect_predictions_is_zero():
    assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0


def test_brier_score_worst_predictions_is_one():
    assert brier_score([0.0, 1.0], [1, 0]) == 1.0


def test_reliability_buckets_shape():
    buckets = reliability_buckets([0.05, 0.15, 0.95], [0, 1, 1], n_bins=10)
    assert len(buckets) == 10
    assert buckets[0]["count"] == 1


def test_expected_calibration_error_bounds():
    ece = expected_calibration_error([0.9] * 10, [1] * 10, n_bins=10)
    assert ece == pytest.approx(0.1, abs=1e-6)
    assert calibration_score_from_ece(ece) == pytest.approx(0.9, abs=1e-6)


def test_hit_rate_and_log_loss():
    assert hit_rate([True, False, True], [True, False, False]) == pytest.approx(2 / 3)
    assert log_loss([0.9, 0.1], [1, 0]) < log_loss([0.5, 0.5], [1, 0])


def test_direction_model_evaluation_bundle():
    evaluation = DirectionModelEvaluation([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0])
    assert evaluation.sample_size == 4
    assert 0.0 <= evaluation.calibration_score <= 1.0


# --------------------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------------------


def test_registry_lookup_miss_by_default():
    registry = ModelRegistry()
    assert registry.lookup("BTCUSDT", "1h", 60) is None
    assert len(registry) == 0


def test_registry_register_and_lookup_roundtrip():
    registry = ModelRegistry()
    weights = LogisticRegressionWeights(
        model_version="v1", feature_names=["adx_14"], up_coefficients=[0.01], up_intercept=0.0,
        down_coefficients=[-0.01], down_intercept=0.0,
    )
    artifact = ModelArtifact(
        symbol="BTCUSDT",
        timeframe="1h",
        horizon_minutes=60,
        model_version="v1",
        feature_version="standard_v1",
        direction_model=LogisticRegressionDirectionModel(weights),
        return_model=LinearReturnModel(
            LinearRegressionWeights(model_version="v1", feature_names=[], coefficients=[], intercept=0.0)
        ),
        volatility_model=RealizedVolatilityModel(),
        meta_label_model=ThresholdMetaLabelModel(),
    )
    registry.register(artifact)
    assert registry.lookup("BTCUSDT", "1h", 60) is artifact
    assert registry.lookup("ETHUSDT", "1h", 60) is None


# --------------------------------------------------------------------------------------
# PredictionService
# --------------------------------------------------------------------------------------


def test_prediction_service_returns_unavailable_when_registry_empty():
    service = PredictionService(registry=ModelRegistry())
    prediction = service.predict("BTCUSDT", "1h", 60, _snapshot())

    assert prediction.calibration_status == CalibrationStatus.UNAVAILABLE
    assert prediction.probability_profit is None
    assert prediction.is_usable is False
    assert "NO_TRAINED_MODEL_ARTIFACT" in prediction.reason_codes


def test_prediction_service_uses_registered_artifact():
    registry = ModelRegistry()
    up_weights = LogisticRegressionWeights(
        model_version="v1", feature_names=["ema_20_slope"], up_coefficients=[100.0], up_intercept=0.0,
        down_coefficients=[-100.0], down_intercept=0.0,
    )
    artifact = ModelArtifact(
        symbol="BTCUSDT",
        timeframe="1h",
        horizon_minutes=60,
        model_version="logreg_v1",
        feature_version="standard_v1",
        direction_model=LogisticRegressionDirectionModel(up_weights),
        return_model=LinearReturnModel(
            LinearRegressionWeights(
                model_version="v1", feature_names=["ema_20_slope"], coefficients=[1000.0], intercept=10.0
            )
        ),
        volatility_model=RealizedVolatilityModel(),
        meta_label_model=ThresholdMetaLabelModel(min_return_to_volatility_ratio=Decimal("0.01")),
        calibration_score=Decimal("0.75"),
    )
    registry.register(artifact)
    service = PredictionService(registry=registry)

    prediction = service.predict("BTCUSDT", "1h", 60, _snapshot(ema_20_slope=Decimal("0.002")))

    assert prediction.calibration_status == CalibrationStatus.CALIBRATED
    assert prediction.probability_profit is not None
    assert prediction.model_version == "logreg_v1"
    assert prediction.is_usable is True


def test_prediction_service_marks_uncalibrated_when_no_calibration_score():
    registry = ModelRegistry()
    weights = LogisticRegressionWeights(
        model_version="v1", feature_names=[], up_coefficients=[], up_intercept=0.5,
        down_coefficients=[], down_intercept=-0.5,
    )
    artifact = ModelArtifact(
        symbol="BTCUSDT",
        timeframe="1h",
        horizon_minutes=60,
        model_version="v1",
        feature_version="standard_v1",
        direction_model=LogisticRegressionDirectionModel(weights),
        return_model=LinearReturnModel(
            LinearRegressionWeights(model_version="v1", feature_names=[], coefficients=[], intercept=5.0)
        ),
        volatility_model=RealizedVolatilityModel(),
        meta_label_model=ThresholdMetaLabelModel(),
        calibration_score=None,
    )
    registry.register(artifact)
    service = PredictionService(registry=registry)

    prediction = service.predict("BTCUSDT", "1h", 60, _snapshot())

    assert prediction.calibration_status == CalibrationStatus.UNCALIBRATED
    assert prediction.is_usable is False
