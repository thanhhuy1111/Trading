"""Phase 4: baseline intelligence services must be honest about what they don't know —
never a fabricated probability, context, edge, or correlation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from packages.candidates.models import CandidateStatus, TradeCandidate
from packages.domain.enums import MetaLabelDecision, RankingStatus
from packages.evidence.models import EvidenceStatus
from packages.intelligence.correlation import BaselineCorrelationService
from packages.intelligence.market_context import BaselineMarketContextService
from packages.intelligence.meta_label import (
    LogisticRegressionMetaLabelService,
    PassThroughMetaLabelService,
    TreeMetaLabelService,
    _score_logistic_regression,
    _score_tree,
)
from packages.intelligence.ranking import BaselineRankingService, RankingInput
from packages.intelligence.strategy_portfolio import StrategyPortfolio, StrategySleeve
from packages.market_data.models import Candle, Timeframe


def _candidate(**overrides) -> TradeCandidate:
    base = dict(
        session_id=uuid4(), symbol="BTC/USDT", timeframe="1h",
        decision_timestamp=datetime.now(timezone.utc), direction="LONG",
        agent_source="trend_agent_v1", agent_confidence=Decimal("0.75"),
        supporting_agents=["trend_agent_v1"], opposing_agents=[],
        consensus_score=Decimal("0.75"), critic_result="trend_agent_v1:APPROVED",
        allocator_result="TRADE_INTENT_CREATED", strategy_name="baseline", strategy_version="1.0.0",
        strategy_config_hash="hash1", market_regime="TREND_UP", feature_snapshot={"rsi_14": "55.0"},
        entry_reference=Decimal("50000"), estimated_fee_bps=Decimal("10"),
        estimated_spread_bps=Decimal("2"), estimated_slippage_bps=Decimal("5"),
        status=CandidateStatus.PROPOSED,
    )
    base.update(overrides)
    return TradeCandidate(**base)


async def test_pass_through_meta_label_never_fabricates_probability() -> None:
    service = PassThroughMetaLabelService()
    pred = await service.predict(_candidate())
    assert pred.probability is None
    assert pred.decision == MetaLabelDecision.DEFER_TO_EXISTING_RULES
    assert "TRAINED_MODEL_NOT_AVAILABLE" in pred.reason_codes


async def test_logistic_regression_service_unavailable_with_empty_registry() -> None:
    from packages.registries.registry import ArtifactRegistry

    empty_registry = ArtifactRegistry("model_test_empty")
    service = LogisticRegressionMetaLabelService(empty_registry)
    pred = await service.predict(_candidate())
    assert pred.probability is None
    assert pred.model_version == "n/a"
    assert pred.decision == MetaLabelDecision.DEFER_TO_EXISTING_RULES


def test_logistic_regression_inference_math_is_correct() -> None:
    artifact = {"feature_names": ["rsi_14"], "coefficients": [0.1], "intercept": -5.0}
    prob, decision = _score_logistic_regression(artifact, {"rsi_14": "55.0"})
    import math
    expected = 1.0 / (1.0 + math.exp(-(-5.0 + 0.1 * 55.0)))
    assert abs(prob - expected) < 1e-9


def test_tree_inference_traverses_to_correct_leaf() -> None:
    artifact = {
        "feature_names": ["rsi_14"],
        "nodes": [
            {"feature_index": 0, "threshold": 50.0, "left": 1, "right": 2},
            {"leaf_value": 0.2},
            {"leaf_value": 0.8},
        ],
    }
    assert _score_tree(artifact, {"rsi_14": "30.0"}) == 0.2
    assert _score_tree(artifact, {"rsi_14": "70.0"}) == 0.8


async def test_tree_service_end_to_end_with_fixture_artifact() -> None:
    from packages.domain.enums import RegistryEntryStatus
    from packages.registries.models import RegistryEntry
    from packages.registries.registry import ArtifactRegistry

    reg = ArtifactRegistry("model_test_tree")
    reg.register(RegistryEntry(
        name="tree_baseline", version="1.0.0", status=RegistryEntryStatus.RESEARCH_ONLY,
        artifact_location="fixture://tree", compatible_symbols=["BTC/USDT"], compatible_timeframes=["1h"],
    ))
    artifact = {
        "feature_names": ["rsi_14"],
        "nodes": [{"leaf_value": 0.9}],
    }
    service = TreeMetaLabelService(reg, artifact_loader=lambda loc: artifact)
    pred = await service.predict(_candidate())
    assert pred.probability == Decimal("0.9")
    assert pred.decision == MetaLabelDecision.ACCEPT
    assert pred.model_version == "1.0.0"


async def test_disabled_market_context_returns_not_available_for_all_agents() -> None:
    service = BaselineMarketContextService()
    results = await service.assess("BTC/USDT", datetime.now(timezone.utc))
    assert len(results) == 4
    for r in results:
        assert r.status.value == "NOT_AVAILABLE"
        assert r.confidence is None
        assert r.view is None
        assert r.risk_adjustment == Decimal("0")
        assert "MARKET_CONTEXT_DISABLED" in r.reason_codes


def test_ranking_missing_edge_falls_back_to_research_only() -> None:
    service = BaselineRankingService()
    inputs = [RankingInput(
        candidate_id=uuid4(), symbol="BTC/USDT", expected_net_edge_bps=None, calibrated_probability=None,
        evidence=None, liquidity_score=Decimal("0.5"), data_freshness_score=Decimal("1.0"),
        cost_bps=Decimal("17"), correlated_exposure_score=Decimal("0"), risk_score=Decimal("0.1"),
    )]
    results = service.rank(inputs)
    assert results[0].ranking_status == RankingStatus.RESEARCH_ONLY
    assert "MISSING_EDGE_OR_PROBABILITY_RESEARCH_FALLBACK" in results[0].reason_codes


def test_ranking_is_deterministic_given_identical_inputs() -> None:
    service = BaselineRankingService()
    inputs = [
        RankingInput(
            candidate_id=uuid4(), symbol="BTC/USDT", expected_net_edge_bps=Decimal("50"),
            calibrated_probability=Decimal("0.6"), evidence=None, liquidity_score=Decimal("0.8"),
            data_freshness_score=Decimal("1.0"), cost_bps=Decimal("17"),
            correlated_exposure_score=Decimal("0"), risk_score=Decimal("0.1"),
        ),
        RankingInput(
            candidate_id=uuid4(), symbol="ETH/USDT", expected_net_edge_bps=Decimal("30"),
            calibrated_probability=Decimal("0.55"), evidence=None, liquidity_score=Decimal("0.6"),
            data_freshness_score=Decimal("1.0"), cost_bps=Decimal("17"),
            correlated_exposure_score=Decimal("0"), risk_score=Decimal("0.1"),
        ),
    ]
    r1 = service.rank(list(inputs))
    r2 = service.rank(list(inputs))
    assert [r.candidate_id for r in r1] == [r.candidate_id for r in r2]
    assert [r.ranking_score for r in r1] == [r.ranking_score for r in r2]


def test_ranking_correlation_penalty_lowers_score() -> None:
    service = BaselineRankingService()
    low_corr = RankingInput(
        candidate_id=uuid4(), symbol="BTC/USDT", expected_net_edge_bps=Decimal("50"),
        calibrated_probability=Decimal("0.6"), evidence=None, liquidity_score=Decimal("0.8"),
        data_freshness_score=Decimal("1.0"), cost_bps=Decimal("17"),
        correlated_exposure_score=Decimal("0"), risk_score=Decimal("0.1"),
    )
    high_corr = RankingInput(
        candidate_id=uuid4(), symbol="ETH/USDT", expected_net_edge_bps=Decimal("50"),
        calibrated_probability=Decimal("0.6"), evidence=None, liquidity_score=Decimal("0.8"),
        data_freshness_score=Decimal("1.0"), cost_bps=Decimal("17"),
        correlated_exposure_score=Decimal("0.9"), risk_score=Decimal("0.1"),
    )
    results = {r.candidate_id: r for r in service.rank([low_corr, high_corr])}
    assert results[low_corr.candidate_id].ranking_score > results[high_corr.candidate_id].ranking_score


def _btc_candle(i: int, price: float) -> Candle:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ct = t0 + timedelta(hours=i)
    from decimal import Decimal as D
    p = D(str(price))
    return Candle(
        exchange="binance", symbol="BTC/USDT", exchange_timestamp=ct, open_time=ct,
        close_time=ct + timedelta(minutes=59), timeframe=Timeframe.H1, open_price=p,
        high_price=p + D("1"), low_price=p - D("1"), close_price=p, volume=D("10"), is_closed=True,
    )


def test_correlation_returns_none_not_zero_when_insufficient_sample() -> None:
    def provider(symbol, timeframe, as_of_time, window_bars):
        return [_btc_candle(i, 100 + i) for i in range(5)]  # far below MINIMUM_SAMPLE_COUNT

    service = BaselineCorrelationService(candles_provider=provider)
    snap = service.snapshot("BTC/USDT", "ETH/USDT", Timeframe.H1, datetime.now(timezone.utc))
    assert snap.correlation is None
    assert snap.status == "INSUFFICIENT_SAMPLE"


def test_correlation_returns_none_when_no_candles_available() -> None:
    service = BaselineCorrelationService(candles_provider=lambda *a: [])
    snap = service.snapshot("BTC/USDT", "ETH/USDT", Timeframe.H1, datetime.now(timezone.utc))
    assert snap.correlation is None
    assert snap.status == "UNAVAILABLE"


def test_correlation_computes_real_value_with_sufficient_sample() -> None:
    def provider(symbol, timeframe, as_of_time, window_bars):
        return [_btc_candle(i, 100 + i) for i in range(50)]  # perfectly correlated with itself

    service = BaselineCorrelationService(candles_provider=provider, max_staleness=timedelta(days=3650))
    snap = service.snapshot("BTC/USDT", "BTC/USDT", Timeframe.H1, datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert snap.correlation is not None
    assert abs(float(snap.correlation) - 1.0) < 1e-6  # a series correlated with itself -> ~1.0


def test_strategy_sleeve_research_only_is_not_approved_eligible() -> None:
    sleeve = StrategySleeve(
        strategy_id="baseline_btc_1h", symbol="BTC/USDT", timeframe="1h", regime_scope=["TREND_UP"],
        risk_budget_pct=0.25, allocation_weight=0.1, evidence_status=EvidenceStatus.RESEARCH_ONLY,
        model_version="n/a", drawdown_limit_pct=8.0,
    )
    assert sleeve.is_approved_eligible is False


def test_strategy_sleeve_approved_evidence_is_eligible() -> None:
    sleeve = StrategySleeve(
        strategy_id="baseline_btc_1h", symbol="BTC/USDT", timeframe="1h", regime_scope=["TREND_UP"],
        risk_budget_pct=0.25, allocation_weight=0.1, evidence_status=EvidenceStatus.ASSET_SPECIFIC_APPROVED,
        model_version="n/a", drawdown_limit_pct=8.0,
    )
    assert sleeve.is_approved_eligible is True


def test_strategy_portfolio_still_returns_research_only_sleeves_for_shadow() -> None:
    portfolio = StrategyPortfolio()
    portfolio.register(StrategySleeve(
        strategy_id="research_sleeve", symbol="BTC/USDT", timeframe="1h", regime_scope=["TREND_UP"],
        risk_budget_pct=0.1, allocation_weight=0.05, evidence_status=EvidenceStatus.RESEARCH_ONLY,
        model_version="n/a", drawdown_limit_pct=8.0,
    ))
    eligible = portfolio.eligible_sleeves("BTC/USDT", "1h", "TREND_UP")
    approved = portfolio.approved_sleeves("BTC/USDT", "1h", "TREND_UP")
    assert len(eligible) == 1
    assert len(approved) == 0
