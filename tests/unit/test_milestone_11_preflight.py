from uuid import uuid4

from packages.telemetry.lineage import lineage_service
from packages.telemetry.metrics import metrics_registry
from packages.telemetry.tracing import tracer


def test_full_pipeline_correlation_chain_trace() -> None:
    """1.3 Full Pipeline Correlation Lineage Chain Evidence."""
    corr_id = uuid4()
    session_id = uuid4()
    symbol = "BTC/USDT"

    # Step 1: MarketEvent
    e_market = lineage_service.record_lineage("MarketEvent", uuid4(), corr_id, session_id=session_id, symbol=symbol)
    # Step 2: FeatureSnapshot
    e_feat = lineage_service.record_lineage(
        "FeatureSnapshot", uuid4(), corr_id, parent_entity_type="MarketEvent",
        parent_entity_id=e_market.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 3: AgentSignal
    e_sig = lineage_service.record_lineage(
        "AgentSignal", uuid4(), corr_id, parent_entity_type="FeatureSnapshot",
        parent_entity_id=e_feat.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 4: CriticDecision
    e_crit = lineage_service.record_lineage(
        "CriticDecision", uuid4(), corr_id, parent_entity_type="AgentSignal",
        parent_entity_id=e_sig.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 5: ConsensusDecision
    e_cons = lineage_service.record_lineage(
        "ConsensusDecision", uuid4(), corr_id, parent_entity_type="CriticDecision",
        parent_entity_id=e_crit.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 6: TradeIntent
    e_intent = lineage_service.record_lineage(
        "TradeIntent", uuid4(), corr_id, parent_entity_type="ConsensusDecision",
        parent_entity_id=e_cons.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 7: RiskDecision
    e_risk = lineage_service.record_lineage(
        "RiskDecision", uuid4(), corr_id, parent_entity_type="TradeIntent",
        parent_entity_id=e_intent.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 8: ApprovedOrder
    e_app_ord = lineage_service.record_lineage(
        "ApprovedOrder", uuid4(), corr_id, parent_entity_type="RiskDecision",
        parent_entity_id=e_risk.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 9: PaperOrder
    e_paper_ord = lineage_service.record_lineage(
        "PaperOrder", uuid4(), corr_id, parent_entity_type="ApprovedOrder",
        parent_entity_id=e_app_ord.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 10: Fill
    e_fill = lineage_service.record_lineage(
        "Fill", uuid4(), corr_id, parent_entity_type="PaperOrder",
        parent_entity_id=e_paper_ord.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 11: LedgerTransaction
    e_tx = lineage_service.record_lineage(
        "LedgerTransaction", uuid4(), corr_id, parent_entity_type="Fill",
        parent_entity_id=e_fill.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 12: PositionEvent
    e_pos = lineage_service.record_lineage(
        "PositionEvent", uuid4(), corr_id, parent_entity_type="LedgerTransaction",
        parent_entity_id=e_tx.entity_id, session_id=session_id, symbol=symbol
    )
    # Step 13: PortfolioSnapshot
    lineage_service.record_lineage(
        "PortfolioSnapshot", uuid4(), corr_id, parent_entity_type="PositionEvent",
        parent_entity_id=e_pos.entity_id, session_id=session_id, symbol=symbol
    )

    chain = lineage_service.get_lineage_by_correlation(corr_id)
    assert len(chain) == 13
    assert chain[0].entity_type == "MarketEvent"
    assert chain[-1].entity_type == "PortfolioSnapshot"
    assert all(c.correlation_id == corr_id for c in chain)


def test_telemetry_failure_isolation() -> None:
    """1.4 Telemetry Failure Isolation Verification."""
    try:
        metrics_registry.increment_counter("trading_system_market_events_total", {"order_id": "FORBIDDEN_KEY"})
    except ValueError:
        pass

    with tracer.start_span("isolated_span") as span:
        span.set_attribute("status", "ISOLATED")
    assert span.status == "OK"
