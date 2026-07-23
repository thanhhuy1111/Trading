"""Unit tests for packages/recommendation/evidence_service.py.

Invariant under test: with the shipped empty registry (no walk-forward backtest evidence
exists yet for any strategy in this repository), every lookup must return INSUFFICIENT --
never an assumed-good or fabricated evidence record.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.recommendation.config import RecommendationConfig
from packages.recommendation.evidence_service import EvidenceRegistry, EvidenceService, evaluate_approval
from packages.recommendation.models import EvidenceStatus, StrategyEvidence

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)

_CONFIG = RecommendationConfig(
    evidence_min_oos_trades=100,
    evidence_min_profit_factor=Decimal("1.20"),
    evidence_min_sharpe=Decimal("1.00"),
    evidence_max_drawdown_pct=Decimal("20.0"),
    evidence_min_walk_forward_windows=3,
    evidence_max_age_days=90,
)


def _evidence(**overrides) -> StrategyEvidence:
    base = dict(
        strategy_name="trend_agent_v1",
        strategy_version="1.0.0",
        model_version="logreg_v1",
        feature_version="standard_v1",
        config_hash="cfg-hash-1",
        status=EvidenceStatus.INSUFFICIENT,
        out_of_sample_trades=250,
        profit_factor=Decimal("1.35"),
        sharpe=Decimal("1.10"),
        maximum_drawdown_pct=Decimal("6.0"),
        expectancy_bps=Decimal("12.0"),
        walk_forward_windows=4,
        created_at=NOW,
    )
    base.update(overrides)
    return StrategyEvidence(**base)


def test_evidence_service_returns_insufficient_when_unregistered():
    service = EvidenceService(registry=EvidenceRegistry(), config=_CONFIG)
    evidence = service.get_evidence("trend_agent_v1", "1.0.0", "cfg-hash-1", "standard_v1", now=NOW)
    assert evidence.status == EvidenceStatus.INSUFFICIENT
    assert "NO_EVIDENCE_RECORDED" in evidence.reason_codes


def test_registry_is_empty_by_default():
    from packages.recommendation.evidence_service import evidence_registry

    assert len(evidence_registry) == 0


def test_evaluate_approval_approves_strong_evidence():
    status, reasons = evaluate_approval(_evidence(), config=_CONFIG, now=NOW)
    assert status == EvidenceStatus.APPROVED
    assert reasons == []


def test_evaluate_approval_insufficient_without_core_metrics():
    thin = _evidence(out_of_sample_trades=0, profit_factor=None, sharpe=None, maximum_drawdown_pct=None)
    status, reasons = evaluate_approval(thin, config=_CONFIG, now=NOW)
    assert status == EvidenceStatus.INSUFFICIENT
    assert "NO_OOS_METRICS_RECORDED" in reasons


def test_evaluate_approval_research_only_when_trade_count_too_low_but_profitable():
    thin = _evidence(out_of_sample_trades=40)
    status, reasons = evaluate_approval(thin, config=_CONFIG, now=NOW)
    assert status == EvidenceStatus.RESEARCH_ONLY
    assert "INSUFFICIENT_OOS_TRADE_COUNT" in reasons


def test_evaluate_approval_rejects_unprofitable_strategy():
    losing = _evidence(profit_factor=Decimal("0.80"), expectancy_bps=Decimal("-3.0"))
    status, reasons = evaluate_approval(losing, config=_CONFIG, now=NOW)
    assert status == EvidenceStatus.REJECTED
    assert "PROFIT_FACTOR_BELOW_THRESHOLD" in reasons


def test_evaluate_approval_rejects_excessive_drawdown_as_research_only_when_still_profitable():
    risky = _evidence(maximum_drawdown_pct=Decimal("35.0"))
    status, reasons = evaluate_approval(risky, config=_CONFIG, now=NOW)
    assert status == EvidenceStatus.RESEARCH_ONLY
    assert "MAX_DRAWDOWN_EXCEEDS_LIMIT" in reasons


def test_evaluate_approval_marks_stale_evidence():
    old = _evidence(created_at=NOW - timedelta(days=200))
    status, reasons = evaluate_approval(old, config=_CONFIG, now=NOW)
    assert status == EvidenceStatus.STALE
    assert "EVIDENCE_OLDER_THAN_MAX_AGE" in reasons


def test_evidence_service_reevaluates_stored_evidence_against_current_policy():
    registry = EvidenceRegistry()
    registry.register(_evidence(status=EvidenceStatus.APPROVED))
    service = EvidenceService(registry=registry, config=_CONFIG)

    fresh = service.get_evidence("trend_agent_v1", "1.0.0", "cfg-hash-1", "standard_v1", now=NOW)
    assert fresh.status == EvidenceStatus.APPROVED

    stale_check = service.get_evidence(
        "trend_agent_v1", "1.0.0", "cfg-hash-1", "standard_v1", now=NOW + timedelta(days=200)
    )
    assert stale_check.status == EvidenceStatus.STALE


def test_evaluate_approval_is_deterministic():
    evidence = _evidence()
    r1 = evaluate_approval(evidence, config=_CONFIG, now=NOW)
    r2 = evaluate_approval(evidence, config=_CONFIG, now=NOW)
    assert r1 == r2
