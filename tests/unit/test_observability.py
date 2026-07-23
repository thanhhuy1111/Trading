from decimal import Decimal
from uuid import uuid4

import pytest

from packages.common.config import settings
from packages.telemetry.alerts import alert_engine
from packages.telemetry.health import health_service
from packages.telemetry.incidents import incident_service
from packages.telemetry.lineage import lineage_service
from packages.telemetry.metrics import metrics_registry
from packages.telemetry.models import (
    ComponentHealthStatus,
    IncidentSeverity,
    IncidentStatus,
    TelemetryContext,
)
from packages.telemetry.redaction import redactor
from packages.telemetry.slo import slo_service
from packages.telemetry.tracing import tracer


def test_metrics_registration_and_cardinality_policy() -> None:
    # Allowed labels
    metrics_registry.increment_counter(
        "trading_system_market_events_total",
        {"service": "market_data", "symbol": "BTC/USDT", "result": "SUCCESS"}
    )
    metrics_registry.set_gauge(
        "trading_system_paper_nav_quote",
        {"service": "paper_trading", "symbol": "BTC/USDT"},
        10485.20
    )

    text = metrics_registry.export_prometheus_text()
    assert "trading_system_market_events_total" in text
    assert "trading_system_paper_nav_quote" in text

    # Forbidden high-cardinality label key should raise ValueError
    with pytest.raises(ValueError, match="CARDINALITY_POLICY_VIOLATION"):
        metrics_registry.increment_counter(
            "trading_system_market_events_total",
            {"order_id": str(uuid4())}  # order_id is forbidden
        )


def test_sensitive_data_redactor() -> None:
    sensitive_dict = {
        "symbol": "BTC/USDT",
        "api_key": "SUPER_SECRET_KEY_123",
        "secret": "TOP_SECRET_PASSWORD",
        "nested": {"password": "PASSWORD123", "normal": "VALUE"}
    }

    redacted = redactor.redact_dict(sensitive_dict)
    assert redacted["symbol"] == "BTC/USDT"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["secret"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["normal"] == "VALUE"

    dsn = "postgresql://admin:secret_pass_123@localhost:5432/trading_db"
    assert "[REDACTED]" in redactor.redact_string(dsn)


def test_distributed_tracing_spans() -> None:
    ctx = TelemetryContext()
    with tracer.start_span("test_pipeline_execution", ctx) as span:
        span.set_attribute("symbol", "BTC/USDT")
        assert span.status == "OK"


def test_health_service_component_lifecycle() -> None:
    health_service.update_component_health("DataGuardian", ComponentHealthStatus.HEALTHY)
    assert health_service.get_system_overall_status() == ComponentHealthStatus.HEALTHY

    health_service.update_component_health("MarketRuntime", ComponentHealthStatus.DEGRADED)
    assert health_service.get_system_overall_status() == ComponentHealthStatus.DEGRADED


def test_slo_error_budget_evaluation() -> None:
    slo_id = list(slo_service.definitions.keys())[0]
    measurement = slo_service.evaluate_slo(slo_id, Decimal("99.95"))
    assert measurement.error_budget_remaining_pct >= Decimal("0.0")


def test_alert_engine_lifecycle() -> None:
    rule_id = list(alert_engine.rules.keys())[0]
    occ1 = alert_engine.trigger_alert(rule_id)
    assert occ1 is not None

    # Deduplicated second trigger
    occ2 = alert_engine.trigger_alert(rule_id)
    assert occ1.occurrence_id == occ2.occurrence_id

    res = alert_engine.resolve_alert(rule_id)
    assert res is not None
    assert res.resolved_at is not None


def test_incident_lifecycle_management() -> None:
    inc = incident_service.report_incident(
        fingerprint="INC_FPRINT_001",
        severity=IncidentSeverity.WARNING,
        component="MarketRuntime",
        incident_type="CONNECTION_DROPPED",
        title="Public Market WebSocket Stream Disconnected",
        description="Public stream dropped connection, initiating REST gap backfill"
    )
    assert inc.status == IncidentStatus.OPEN

    # Transition: OPEN -> ACKNOWLEDGED -> INVESTIGATING -> RESOLVED -> CLOSED
    inc2 = incident_service.transition_incident(inc.incident_id, IncidentStatus.ACKNOWLEDGED, actor="operator")
    assert inc2.status == IncidentStatus.ACKNOWLEDGED

    inc3 = incident_service.transition_incident(inc.incident_id, IncidentStatus.INVESTIGATING, actor="operator")
    assert inc3.status == IncidentStatus.INVESTIGATING

    inc4 = incident_service.transition_incident(
        inc.incident_id, IncidentStatus.RESOLVED, actor="operator", reason="Stream re-established"
    )
    assert inc4.status == IncidentStatus.RESOLVED

    inc5 = incident_service.transition_incident(inc.incident_id, IncidentStatus.CLOSED, actor="operator")
    assert inc5.status == IncidentStatus.CLOSED

    # Invalid transition (CLOSED -> OPEN) must raise ValueError
    with pytest.raises(ValueError, match="INVALID_INCIDENT_TRANSITION"):
        incident_service.transition_incident(inc.incident_id, IncidentStatus.OPEN)


def test_pipeline_lineage_correlation() -> None:
    corr_id = uuid4()
    r1 = lineage_service.record_lineage("MarketEvent", uuid4(), corr_id, symbol="BTC/USDT")
    lineage_service.record_lineage(
        "AgentSignal",
        uuid4(),
        corr_id,
        parent_entity_type="MarketEvent",
        parent_entity_id=r1.entity_id,
        symbol="BTC/USDT"
    )

    chain = lineage_service.get_lineage_by_correlation(corr_id)
    assert len(chain) == 2
    assert chain[0].entity_type == "MarketEvent"
    assert chain[1].entity_type == "AgentSignal"


def test_observability_safety_invariants() -> None:
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.SYSTEM_MODE in ["SIMULATION", "MINIMAL", "PAPER_TRADING", "DEVELOPMENT", "TEST"]
