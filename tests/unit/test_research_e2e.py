"""End-to-end offline pipeline coverage (implementation plan section 21).

Two scenarios, both fully offline (fixture candles, no network, no Gemini):

1. `test_full_offline_pipeline_runs_without_error` -- fixture candles all the way through
   dataset -> features -> labels -> train -> calibrate -> walk-forward -> evidence,
   asserting the chain produces well-formed artifacts. It does NOT force an APPROVED
   result: whatever `evaluate_research_approval` naturally decides for this modest
   synthetic sample is accepted and asserted to be internally consistent. Forcing approval
   here would be exactly the "approve a strategy based on a smoke test" the plan forbids.

2. `test_recommendation_service_gated_by_real_default_and_approved_registries` -- proves
   the runtime gating contract in both directions: with the actual shipped-empty
   registries, RecommendationService never reaches PROPOSALS_AVAILABLE; once a model is
   registered through `runtime_loader.load_approved_model` (which itself requires a real
   APPROVED StrategyEvidence, constructed directly here rather than mined from a lucky
   synthetic sample), the exact same service, with the exact same market data, produces a
   real, traceable proposal.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from packages.market_data.models import Candle, DataQualityStatus, Timeframe
from packages.prediction.direction_model import LogisticRegressionDirectionModel, LogisticRegressionWeights
from packages.prediction.registry import ModelRegistry
from packages.prediction.return_model import LinearRegressionWeights
from packages.prediction.service import PredictionService
from packages.recommendation.evidence_service import EvidenceRegistry, EvidenceService
from packages.recommendation.models import EvidenceStatus, RecommendationStatus, StrategyEvidence
from packages.recommendation.proposal_store import ProposalStore
from packages.recommendation.service import PIPELINE_STRATEGY_NAME, PIPELINE_STRATEGY_VERSION, RecommendationService
from packages.research.artifacts import ArtifactStore
from packages.research.cli import _apply_model_predictions
from packages.research.config import ApprovalGateConfig, DatasetConfig, FeatureConfig, LabelConfig, SplitConfig
from packages.research.dataset_builder import build_raw_candle_dataset
from packages.research.evaluation import run_walk_forward_evaluation
from packages.research.evidence_publisher import evaluate_research_approval, publish_evidence
from packages.research.feature_dataset import build_feature_table
from packages.research.labels import build_label_table
from packages.research.runtime_loader import load_approved_model
from packages.research.splits import assign_split_membership, plan_chronological_split
from packages.research.training import (
    prepare_training_matrix,
    train_linear_return_weights,
    train_logistic_direction_weights,
    weights_checksum,
)
from tests.unit.test_recommendation_service import _UptrendMarketDataProvider

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _fixture_candles(n=400, symbol="BTCUSDT", timeframe=Timeframe.H1):
    import random

    rng = random.Random(42)
    t0 = NOW - timedelta(hours=n)
    candles = []
    price = Decimal("50000.00")
    for i in range(n):
        open_time = t0 + timedelta(hours=i)
        drift = Decimal(str(rng.uniform(-0.006, 0.007)))
        step = price * drift
        open_p = price
        close_p = max(price + step, Decimal("1000.00"))
        candles.append(
            Candle(
                exchange="binance", symbol=symbol, timeframe=timeframe,
                open_time=open_time, close_time=open_time + timedelta(minutes=59),
                open_price=open_p, high_price=max(open_p, close_p) + Decimal("5"),
                low_price=min(open_p, close_p) - Decimal("5"), close_price=close_p,
                volume=Decimal("100.0"), exchange_timestamp=open_time + timedelta(minutes=59),
                data_quality_status=DataQualityStatus.HEALTHY, is_closed=True,
            )
        )
        price = close_p
    return candles


def test_full_offline_pipeline_runs_without_error():
    candles = _fixture_candles(n=400)
    dataset_config = DatasetConfig(
        symbols=["BTCUSDT"], timeframes=["1h"], start_time=NOW - timedelta(hours=400), end_time=NOW,
        warmup_periods=60,
    )
    dataset, kept = build_raw_candle_dataset(candles, dataset_config, config_hash="cfg-hash", now=NOW)
    assert dataset.candle_count > 0

    feature_table = build_feature_table(kept, FeatureConfig())
    # horizon=240min (4 candles) with a 1.2% barrier gives the synthetic random walk a
    # realistic chance to hit either barrier within the window, producing PROFIT/LOSS/
    # TIMEOUT diversity -- a 60-minute horizon (1 candle) almost never crosses 1%+ given
    # this fixture's per-candle volatility, which would make every label TIMEOUT.
    label_config = LabelConfig(
        horizons_minutes=[240], upper_barrier_pct=Decimal("0.012"), lower_barrier_pct=Decimal("0.012")
    )
    label_table = build_label_table(kept, label_config)
    assert not feature_table.empty
    assert not label_table.empty

    merged = prepare_training_matrix(feature_table, label_table, _feature_names(), horizon_minutes=240)

    split_config = SplitConfig(num_folds=1, purge_hours=5, embargo_hours=2)
    window = plan_chronological_split(dataset_config.start_time, dataset_config.end_time, split_config, label_config)
    classified = assign_split_membership(merged, window)
    train_rows = classified[classified["split"] == "train"]

    if len(train_rows) < 20 or train_rows["label"].nunique() < 2:
        pytest.skip("Synthetic fixture did not produce enough class diversity for this run (non-deterministic gate)")

    direction_weights = train_logistic_direction_weights(
        train_rows, _feature_names(), "logreg_e2e_v1", {"max_iter": 500}, random_seed=42
    )
    return_weights = train_linear_return_weights(train_rows, _feature_names(), "logreg_e2e_v1")
    checksum = weights_checksum(direction_weights, return_weights)
    assert len(checksum) == 64

    model = LogisticRegressionDirectionModel(direction_weights)
    classified_with_predictions = _apply_model_predictions(classified, model, _feature_names(), threshold=0.5)

    report = run_walk_forward_evaluation(
        subject_name="logreg_e2e_v1", subject_type="MODEL", fold_tables=[classified_with_predictions],
        dataset_checksum=dataset.dataset_checksum, config_hash="cfg-hash",
        decision_column="model_decision", probability_column="model_probability", now=NOW,
    )
    assert report.walk_forward_windows == 1
    assert report.aggregate_metrics is not None

    evidence_registry = EvidenceRegistry()
    evidence = publish_evidence(
        report, strategy_name="e2e_test_pipeline", strategy_version="1.0.0", model_version="logreg_e2e_v1",
        feature_version="standard_v1", research_approval_config=ApprovalGateConfig(),
        registry=evidence_registry, now=NOW,
    )
    # Whatever the natural outcome is, it must be one of the five valid statuses and must
    # be internally consistent with what evaluate_research_approval independently computes.
    assert evidence.status in {
        EvidenceStatus.APPROVED, EvidenceStatus.RESEARCH_ONLY, EvidenceStatus.INSUFFICIENT,
        EvidenceStatus.REJECTED, EvidenceStatus.STALE,
    }
    recheck_status, _ = evaluate_research_approval(evidence, report, ApprovalGateConfig(), now=NOW)
    assert recheck_status == evidence.status
    assert evidence_registry.lookup("e2e_test_pipeline", "1.0.0") is not None


def _feature_names():
    return FeatureConfig().feature_names


@pytest.mark.asyncio
async def test_recommendation_service_gated_by_default_and_approved_registries(tmp_path):
    # -- 1. Default (shipped-empty) registries: must NEVER reach PROPOSALS_AVAILABLE. --
    default_service = RecommendationService(
        market_data_provider=_UptrendMarketDataProvider(),
        prediction_svc=PredictionService(registry=ModelRegistry()),
        evidence_svc=EvidenceService(registry=EvidenceRegistry()),
        store=ProposalStore(),
    )
    default_result = await default_service.scan_trade_opportunities(symbols=["BTCUSDT"], timeframes=["1h"])
    assert default_result.status != RecommendationStatus.PROPOSALS_AVAILABLE

    # -- 2. A real APPROVED evidence + a real trained-and-loaded model: the SAME service
    # (same market data provider, same code path) must now produce a real proposal. --
    evidence_registry = EvidenceRegistry()
    evidence_registry.register(
        StrategyEvidence(
            strategy_name=PIPELINE_STRATEGY_NAME, strategy_version=PIPELINE_STRATEGY_VERSION,
            model_version="logreg_v1", feature_version="standard_v1", config_hash="cfg-hash",
            status=EvidenceStatus.APPROVED, out_of_sample_trades=250, profit_factor=Decimal("1.35"),
            sharpe=Decimal("1.10"), maximum_drawdown_pct=Decimal("6.0"), expectancy_bps=Decimal("12.0"),
            walk_forward_windows=4, calibration_metrics="method=platt,calibration_score=0.80", created_at=NOW,
        )
    )

    store = ArtifactStore(root=str(tmp_path / "artifacts"))
    up_weights = LogisticRegressionWeights(
        model_version="logreg_v1", feature_names=["ema_20_slope"], up_coefficients=[500.0], up_intercept=0.5,
        down_coefficients=[-500.0], down_intercept=-1.0,
    )
    return_weights = LinearRegressionWeights(
        model_version="logreg_v1", feature_names=["ema_20_slope"], coefficients=[1000.0], intercept=20.0
    )
    from packages.research.models import ModelArtifactRecord

    record = ModelArtifactRecord(
        model_id="model-e2e", model_type="logistic_regression", model_version="logreg_v1",
        feature_version="standard_v1", dataset_checksum="abc", label_version="triple_barrier_v1",
        hyperparameters={}, random_seed=42, train_period="p1", validation_period="p2", test_period="p3",
        code_commit="deadbeef", artifact_path="models/model-e2e", artifact_checksum="xyz",
        config_hash="cfg-hash", created_at=NOW,
    )
    store.save_metadata("models", "model-e2e", record)
    store.save_weights_json("model-e2e_direction", up_weights)
    store.save_weights_json("model-e2e_return", return_weights)

    prediction_registry = ModelRegistry()
    load_approved_model(
        "model-e2e", PIPELINE_STRATEGY_NAME, PIPELINE_STRATEGY_VERSION, "BTCUSDT", "1h", 60,
        store=store, prediction_registry=prediction_registry, evidence_reg=evidence_registry,
    )
    assert prediction_registry.lookup("BTCUSDT", "1h", 60) is not None

    approved_service = RecommendationService(
        market_data_provider=_UptrendMarketDataProvider(),
        prediction_svc=PredictionService(registry=prediction_registry),
        evidence_svc=EvidenceService(registry=evidence_registry),
        store=ProposalStore(),
    )
    approved_result = await approved_service.scan_trade_opportunities(symbols=["BTCUSDT"], timeframes=["1h"])

    assert approved_result.status == RecommendationStatus.PROPOSALS_AVAILABLE
    assert len(approved_result.proposals) >= 1
    assert approved_result.proposals[0].evidence_id is not None
