"""Architecture / no-fabrication guards for the paper decision pipeline (F-01).

These tests fail if the paper pipeline reverts to fabricating TradeIntents, or if the
shared decision service stops using the real agents / critic / consensus / allocator.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_paper_pipeline_uses_decision_service_and_not_fabrication() -> None:
    src = _read("packages/paper/pipeline.py")
    # Real pipeline is invoked
    assert "decision_service" in src
    assert "decision_service.decide(" in src
    # No fabricated confidence / edge / regime literals remain
    assert '0.85' not in src, "fabricated weighted_confidence must be removed"
    assert 'net_edge_bps=Decimal("120' not in src, "fabricated net edge must be removed"
    assert "market_regime=MarketRegime.TREND_UP" not in src, "fabricated regime must be removed"


def test_decision_service_uses_real_components() -> None:
    src = _read("packages/governance/decision_service.py")
    for component in [
        "TrendAgent",
        "MeanReversionAgent",
        "BreakoutAgent",
        "MarketRegimeAgent",
        "critic_agent",
        "signal_consensus_engine",
        "meta_allocator",
        "feature_pipeline",
    ]:
        assert component in src, f"decision_service must use real component {component}"


def test_no_hardcoded_reference_price_in_agents_or_allocator() -> None:
    for rel in [
        "packages/agents/trend.py",
        "packages/agents/reversion.py",
        "packages/agents/breakout.py",
        "packages/governance/allocator.py",
    ]:
        assert "65000" not in _read(rel), f"hardcoded reference price must be removed from {rel}"
