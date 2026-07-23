"""Unit tests for packages/recommendation: builder, validator, ranker, cost service.

All fixtures are hand-built TradeCandidate/ModelPrediction/StrategyEvidence objects --
no network, no DB, no LLM. These pin down the domain's determinism and NO_TRADE/
INSUFFICIENT_EVIDENCE safety behaviour independent of the live market-data pipeline.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from packages.prediction.models import CalibrationStatus, ModelPrediction
from packages.recommendation.config import RecommendationConfig
from packages.recommendation.cost_service import recommendation_cost_service
from packages.recommendation.models import DecisionLineage, EvidenceStatus, StrategyEvidence, TradeCandidate
from packages.recommendation.opportunity_ranker import opportunity_ranker
from packages.recommendation.proposal_builder import proposal_builder
from packages.recommendation.proposal_validator import check_candidate_gates, validate_proposal

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _lineage() -> DecisionLineage:
    return DecisionLineage(
        feature_snapshot_id="fs-1",
        market_regime="TREND_UP",
        signal_ids=["sig-1", "sig-2"],
        critic_decision_ids=["crit-1", "crit-2"],
        consensus_id="cons-1",
        allocation_id="alloc-1",
        trade_intent_id="intent-1",
        config_hash="cfg-hash-1",
    )


def _candidate(**overrides) -> TradeCandidate:
    base = dict(
        symbol="BTCUSDT",
        side="BUY",
        timeframe="1h",
        horizon_minutes=60,
        strategy_names=["trend_agent_v1"],
        strategy_version="1.0.0",
        reference_price=Decimal("65000.00"),
        stop_loss=Decimal("63050.00"),
        take_profit=Decimal("68250.00"),
        raw_confidence=Decimal("0.75"),
        expected_return_bps=Decimal("375.0"),
        net_edge_bps=Decimal("353.0"),
        market_regime="TREND_UP",
        liquidity_score=Decimal("0.90"),
        spread_bps=Decimal("2.0"),
        reason_codes=["UPTREND_CONFIRMED"],
        feature_snapshot_id="fs-1",
        feature_set_version="standard_v1",
        data_timestamp=NOW,
        freshness_seconds=5.0,
        config_hash="cfg-hash-1",
        decision_lineage=_lineage(),
    )
    base.update(overrides)
    return TradeCandidate(**base)


def _prediction(**overrides) -> ModelPrediction:
    base = dict(
        symbol="BTCUSDT",
        timeframe="1h",
        horizon_minutes=60,
        probability_up=Decimal("0.65"),
        probability_down=Decimal("0.35"),
        probability_flat=Decimal("0.0"),
        probability_profit=Decimal("0.65"),
        expected_return_bps=Decimal("300.0"),
        expected_volatility_bps=Decimal("150.0"),
        calibration_status=CalibrationStatus.CALIBRATED,
        calibration_score=Decimal("0.72"),
        model_version="logreg_v1",
        feature_snapshot_id="fs-1",
        generated_at=NOW,
    )
    base.update(overrides)
    return ModelPrediction(**base)


def _unavailable_prediction() -> ModelPrediction:
    return ModelPrediction(
        symbol="BTCUSDT",
        timeframe="1h",
        horizon_minutes=60,
        calibration_status=CalibrationStatus.UNAVAILABLE,
        model_version="none",
        feature_snapshot_id="fs-1",
        generated_at=NOW,
        reason_codes=["NO_TRAINED_MODEL_ARTIFACT"],
    )


def _approved_evidence() -> StrategyEvidence:
    return StrategyEvidence(
        strategy_name="trend_agent_v1",
        strategy_version="1.0.0",
        model_version="logreg_v1",
        feature_version="standard_v1",
        config_hash="cfg-hash-1",
        status=EvidenceStatus.APPROVED,
        out_of_sample_trades=250,
        profit_factor=Decimal("1.35"),
        sharpe=Decimal("1.10"),
        maximum_drawdown_pct=Decimal("6.0"),
        created_at=NOW,
    )


def _insufficient_evidence() -> StrategyEvidence:
    return StrategyEvidence(
        strategy_name="trend_agent_v1",
        strategy_version="1.0.0",
        model_version="none",
        feature_version="standard_v1",
        config_hash="cfg-hash-1",
        status=EvidenceStatus.INSUFFICIENT,
        created_at=NOW,
    )


# --------------------------------------------------------------------------------------
# Cost service
# --------------------------------------------------------------------------------------


def test_cost_service_matches_governance_cost_estimator():
    cost = recommendation_cost_service.estimate("BTCUSDT")
    assert cost.total_cost_bps == cost.fee_bps + cost.spread_bps + cost.slippage_bps + cost.uncertainty_buffer_bps
    assert cost.total_cost_bps > Decimal("0")


# --------------------------------------------------------------------------------------
# Proposal builder
# --------------------------------------------------------------------------------------


def test_builder_produces_proposal_with_real_traceable_fields():
    candidate = _candidate()
    prediction = _prediction()
    evidence = _approved_evidence()

    proposal = proposal_builder.build(candidate, prediction, evidence, now=NOW)

    assert proposal is not None
    assert proposal.symbol == "BTCUSDT"
    assert proposal.side == "BUY"
    assert proposal.status.value == "PROPOSED"
    assert proposal.entry_from == candidate.reference_price
    assert proposal.entry_to > proposal.entry_from
    assert proposal.stop_loss == candidate.stop_loss
    assert proposal.take_profit_levels == [candidate.take_profit]
    assert proposal.probability_profit == prediction.probability_profit
    assert proposal.expected_gross_return_bps == candidate.expected_return_bps
    assert proposal.risk_reward_ratio > Decimal("0")
    assert proposal.decision_lineage.trade_intent_id == "intent-1"
    assert proposal.decision_lineage.prediction_id == prediction.prediction_id
    assert proposal.decision_lineage.evidence_id == evidence.evidence_id
    assert proposal.expires_at > proposal.generated_at
    assert proposal.is_simulated is False


def test_builder_returns_none_when_prediction_unavailable():
    """The core no-fabrication invariant: no model artifact -> no proposal, ever."""
    candidate = _candidate()
    prediction = _unavailable_prediction()
    evidence = _approved_evidence()

    proposal = proposal_builder.build(candidate, prediction, evidence, now=NOW)

    assert proposal is None


def test_builder_returns_none_when_risk_reward_undefined():
    candidate = _candidate(stop_loss=Decimal("65000.00"))  # stop == entry -> zero risk denominator
    prediction = _prediction()
    evidence = _approved_evidence()

    proposal = proposal_builder.build(candidate, prediction, evidence, now=NOW)

    assert proposal is None


def test_builder_is_deterministic_for_identical_inputs():
    candidate = _candidate()
    prediction = _prediction()
    evidence = _approved_evidence()

    p1 = proposal_builder.build(candidate, prediction, evidence, now=NOW)
    p2 = proposal_builder.build(candidate, prediction, evidence, now=NOW)

    assert p1.opportunity_score == p2.opportunity_score
    assert p1.risk_reward_ratio == p2.risk_reward_ratio
    assert p1.expected_net_return_bps == p2.expected_net_return_bps


# --------------------------------------------------------------------------------------
# Opportunity ranker
# --------------------------------------------------------------------------------------


def test_ranker_orders_by_score_descending():
    candidate = _candidate()
    prediction = _prediction()
    evidence = _approved_evidence()
    strong = proposal_builder.build(candidate, prediction, evidence, now=NOW)

    weak_candidate = _candidate(net_edge_bps=Decimal("1.0"), liquidity_score=Decimal("0.45"))
    weak_prediction = _prediction(probability_profit=Decimal("0.59"))
    weak = proposal_builder.build(weak_candidate, weak_prediction, evidence, now=NOW)

    ranked = opportunity_ranker.rank([weak, strong])

    assert ranked[0].proposal_id == strong.proposal_id
    assert ranked[0].opportunity_score >= ranked[1].opportunity_score


def test_ranker_respects_max_results():
    candidate = _candidate()
    prediction = _prediction()
    evidence = _approved_evidence()
    proposals = [proposal_builder.build(candidate, prediction, evidence, now=NOW) for _ in range(5)]

    ranked = opportunity_ranker.rank(proposals, max_results=3)

    assert len(ranked) == 3


# --------------------------------------------------------------------------------------
# Candidate gates (proposal_validator.check_candidate_gates)
# --------------------------------------------------------------------------------------


def test_candidate_gates_pass_for_healthy_candidate():
    passed, reasons = check_candidate_gates(_candidate(), _prediction(), _approved_evidence())
    assert passed is True
    assert reasons == []


def test_candidate_gates_reject_stale_market_data():
    stale = _candidate(freshness_seconds=999.0)
    passed, reasons = check_candidate_gates(stale, _prediction(), _approved_evidence())
    assert passed is False
    assert "MARKET_DATA_STALE" in reasons


def test_candidate_gates_reject_unsupported_symbol():
    exotic = _candidate(symbol="DOGEUSDT")
    passed, reasons = check_candidate_gates(exotic, _prediction(), _approved_evidence())
    assert passed is False
    assert "SYMBOL_NOT_SUPPORTED" in reasons


def test_candidate_gates_reject_when_prediction_unavailable():
    passed, reasons = check_candidate_gates(_candidate(), _unavailable_prediction(), _approved_evidence())
    assert passed is False
    assert "INSUFFICIENT_EVIDENCE_PREDICTION_UNAVAILABLE" in reasons


def test_candidate_gates_reject_when_strategy_not_approved():
    passed, reasons = check_candidate_gates(_candidate(), _prediction(), _insufficient_evidence())
    assert passed is False
    assert "STRATEGY_NOT_APPROVED" in reasons


def test_candidate_gates_reject_probability_below_threshold():
    weak_prediction = _prediction(probability_profit=Decimal("0.50"))
    passed, reasons = check_candidate_gates(_candidate(), weak_prediction, _approved_evidence())
    assert passed is False
    assert "PROBABILITY_BELOW_THRESHOLD" in reasons


def test_candidate_gates_reject_non_positive_net_edge():
    losing = _candidate(net_edge_bps=Decimal("-5.0"))
    passed, reasons = check_candidate_gates(losing, _prediction(), _approved_evidence())
    assert passed is False
    assert "EXPECTED_NET_RETURN_NOT_POSITIVE" in reasons


def test_candidate_gates_reject_unknown_regime():
    unknown = _candidate(market_regime="UNKNOWN")
    passed, reasons = check_candidate_gates(unknown, _prediction(), _approved_evidence())
    assert passed is False
    assert "REGIME_UNKNOWN" in reasons


# --------------------------------------------------------------------------------------
# Proposal revalidation (validate_trade_proposal tool logic)
# --------------------------------------------------------------------------------------


def test_validate_proposal_valid_when_fresh():
    proposal = proposal_builder.build(_candidate(), _prediction(), _approved_evidence(), now=NOW)
    result = validate_proposal(proposal, now=NOW + timedelta(seconds=30))
    assert result.valid is True
    assert result.reason_codes == []


def test_validate_proposal_rejects_after_expiry():
    proposal = proposal_builder.build(_candidate(), _prediction(), _approved_evidence(), now=NOW)
    result = validate_proposal(proposal, now=proposal.expires_at + timedelta(seconds=1))
    assert result.valid is False
    assert "PROPOSAL_EXPIRED" in result.reason_codes


def test_validate_proposal_rejects_stale_data_even_before_expiry():
    config = RecommendationConfig(max_market_data_staleness_seconds=30)
    proposal = proposal_builder.build(_candidate(), _prediction(), _approved_evidence(), config=config, now=NOW)
    result = validate_proposal(proposal, config=config, now=NOW + timedelta(seconds=60))
    assert result.valid is False
    assert "MARKET_DATA_STALE" in result.reason_codes


@pytest.mark.parametrize("field", ["probability_profit", "risk_reward_ratio"])
def test_validate_proposal_is_a_pure_function_of_inputs(field):
    proposal = proposal_builder.build(_candidate(), _prediction(), _approved_evidence(), now=NOW)
    r1 = validate_proposal(proposal, now=NOW + timedelta(minutes=1))
    r2 = validate_proposal(proposal, now=NOW + timedelta(minutes=1))
    assert r1.valid == r2.valid
    assert r1.reason_codes == r2.reason_codes
