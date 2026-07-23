"""Phase 1: domain entities must serialize, version, reject invalid states, and keep
immutable identifiers stable."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.domain.entities import (
    CorrelationSnapshot,
    ModelPrediction,
    PortfolioRiskDecision,
    ReadinessStatus,
    ShadowOutcome,
    ShadowProposal,
    TradeProposal,
    stable_checksum,
)
from packages.domain.enums import (
    ArchitectureReadiness,
    EvidenceReadiness,
    LiveReadiness,
    MetaLabelDecision,
    ModelReadiness,
    ModelType,
    PortfolioRiskDecisionType,
    ShadowOutcomeStatus,
    ShadowProposalKind,
    StrategyReadiness,
)


def _readiness(**overrides) -> ReadinessStatus:
    base = dict(
        architecture_readiness=ArchitectureReadiness.READY,
        strategy_readiness=StrategyReadiness.RESEARCH_ONLY,
        model_readiness=ModelReadiness.BASELINE,
        evidence_readiness=EvidenceReadiness.NO_APPROVED_STRATEGY,
        shadow_readiness="READY",
    )
    base.update(overrides)
    return ReadinessStatus(**base)


def test_readiness_status_round_trips_through_json() -> None:
    rs = _readiness()
    dumped = rs.model_dump_json()
    restored = ReadinessStatus.model_validate_json(dumped)
    assert restored.architecture_readiness == rs.architecture_readiness
    assert restored.live_readiness == LiveReadiness.DISABLED


def test_readiness_status_defaults_live_readiness_to_disabled() -> None:
    rs = _readiness()
    assert rs.live_readiness == LiveReadiness.DISABLED


def test_readiness_status_rejects_invalid_enum_value() -> None:
    with pytest.raises(ValidationError):
        _readiness(architecture_readiness="SOMETHING_MADE_UP")


def test_model_prediction_baseline_has_null_probability() -> None:
    pred = ModelPrediction(
        candidate_id=uuid4(), model_type=ModelType.PASS_THROUGH, model_version="n/a",
        feature_version="standard_v1", label_version="meta_label_v1",
        decision=MetaLabelDecision.DEFER_TO_EXISTING_RULES,
        reason_codes=["TRAINED_MODEL_NOT_AVAILABLE"],
    )
    assert pred.probability is None
    assert pred.decision == MetaLabelDecision.DEFER_TO_EXISTING_RULES


def test_shadow_proposal_is_immutable() -> None:
    sp = ShadowProposal(
        kind=ShadowProposalKind.RESEARCH_SHADOW, proposal_id=uuid4(),
        candidate_snapshot={"a": 1}, feature_snapshot={}, regime_snapshot={},
        agent_assessments_snapshot=[], meta_label_snapshot={}, market_context_snapshot=[],
        evidence_snapshot={}, ranking_snapshot={}, portfolio_risk_snapshot={},
        market_data_timestamp=datetime.now(timezone.utc), code_commit="abc123",
        configuration_versions={"gate_version": "gate_v1"},
    )
    with pytest.raises(ValidationError):
        sp.candidate_snapshot = {"tampered": True}


def test_shadow_proposal_checksum_is_deterministic_for_same_content() -> None:
    kwargs = dict(
        kind=ShadowProposalKind.APPROVED_SHADOW, proposal_id=uuid4(),
        candidate_snapshot={"x": 1}, feature_snapshot={}, regime_snapshot={},
        agent_assessments_snapshot=[], meta_label_snapshot={}, market_context_snapshot=[],
        evidence_snapshot={}, ranking_snapshot={}, portfolio_risk_snapshot={},
        market_data_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), code_commit="abc123",
        configuration_versions={"gate_version": "gate_v1"},
    )
    sp1 = ShadowProposal(**kwargs)
    sp2 = ShadowProposal(**kwargs)
    assert sp1.compute_checksum() == sp2.compute_checksum()


def test_shadow_outcome_defaults_to_pending() -> None:
    out = ShadowOutcome(shadow_id=uuid4(), evaluation_due_at=datetime.now(timezone.utc))
    assert out.status == ShadowOutcomeStatus.PENDING
    assert out.net_return_bps is None


def test_correlation_snapshot_missing_correlation_is_none_not_zero() -> None:
    snap = CorrelationSnapshot(
        window_config_version="corr_v1", symbol_a="BTC/USDT", symbol_b="ETH/USDT",
        timeframe="1h", window_bars=100, sample_count=3, correlation=None,
        status="INSUFFICIENT_SAMPLE", reason_codes=["MIN_SAMPLE_NOT_MET"],
    )
    assert snap.correlation is None  # never silently defaulted to 0.0


def test_portfolio_risk_decision_requires_explicit_type() -> None:
    decision = PortfolioRiskDecision(
        policy_version="risk_v1", decision=PortfolioRiskDecisionType.REJECT,
        requested_risk_pct=Decimal("0.25"), approved_risk_pct=Decimal("0"),
        reason_codes=["DAILY_LOSS_LIMIT_EXCEEDED"],
    )
    assert decision.decision == PortfolioRiskDecisionType.REJECT
    assert decision.approved_risk_pct == Decimal("0")


def test_trade_proposal_null_fields_stay_null() -> None:
    from packages.domain.enums import ApplicationResultState

    proposal = TradeProposal(
        candidate_id=uuid4(), symbol="BTC/USDT", timeframe="1h", direction="LONG",
        entry_reference=Decimal("50000"), estimated_fee_bps=Decimal("10"),
        estimated_spread_bps=Decimal("2"), estimated_slippage_bps=Decimal("5"),
        strategy_version="1.0.0", model_version="n/a", evidence_status="RESEARCH_ONLY",
        proposal_expiry=datetime.now(timezone.utc),
        application_result_state=ApplicationResultState.RESEARCH_PROPOSAL,
    )
    # Fields with no real value must stay None, never fabricated to satisfy the schema.
    assert proposal.expected_net_return_bps is None
    assert proposal.calibrated_probability is None
    assert proposal.ranking_score is None


def test_stable_checksum_is_order_independent() -> None:
    a = stable_checksum({"x": 1, "y": 2})
    b = stable_checksum({"y": 2, "x": 1})
    assert a == b


def test_stable_checksum_changes_with_content() -> None:
    a = stable_checksum({"x": 1})
    b = stable_checksum({"x": 2})
    assert a != b
