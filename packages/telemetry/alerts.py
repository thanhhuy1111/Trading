from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.telemetry.models import AlertOccurrence, AlertRule, IncidentSeverity


class AlertEngine:
    """Manages alert rule definitions, threshold duration evaluation, and anti-noise controls."""

    def __init__(self) -> None:
        self.rules: Dict[UUID, AlertRule] = {}
        self.active_alerts: Dict[UUID, AlertOccurrence] = {}
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        defaults = [
            AlertRule(
                name="MarketDataStreamDisconnected",
                description="Public market WebSocket connection lost or unresponsive",
                severity=IncidentSeverity.WARNING,
                component="MarketDataRuntime",
                for_duration_seconds=30,
                runbook_url="/docs/OBSERVABILITY_RUNBOOK.md#market-stream-disconnected"
            ),
            AlertRule(
                name="RiskGovernorKillSwitchActive",
                description="Deterministic Risk Governor triggered Hard Stop due to loss or drawdown breach",
                severity=IncidentSeverity.CRITICAL,
                component="RiskGovernor",
                for_duration_seconds=0,
                runbook_url="/docs/OBSERVABILITY_RUNBOOK.md#risk-hard-stop"
            ),
            AlertRule(
                name="ExecutionReconciliationFailure",
                description="Position or ledger reconciliation audit detected completeness mismatch",
                severity=IncidentSeverity.ERROR,
                component="PositionManager",
                for_duration_seconds=0,
                runbook_url="/docs/OBSERVABILITY_RUNBOOK.md#position-reconciliation-failure"
            ),
        ]
        for rule in defaults:
            self.rules[rule.rule_id] = rule

    def trigger_alert(self, rule_id: UUID) -> AlertOccurrence:
        rule = self.rules.get(rule_id)
        if not rule:
            raise ValueError(f"ALERT_ERROR: Rule {rule_id} not found")

        if rule_id in self.active_alerts:
            # Alert already active (deduplicated)
            return self.active_alerts[rule_id]

        occ = AlertOccurrence(
            occurrence_id=uuid4(),
            rule_id=rule_id,
            severity=rule.severity,
            triggered_at=datetime.now(timezone.utc)
        )

        self.active_alerts[rule_id] = occ
        logger.warning("Alert rule triggered", extra={"alert_name": rule.name, "severity": rule.severity.value})
        return occ

    def resolve_alert(self, rule_id: UUID) -> Optional[AlertOccurrence]:
        occ = self.active_alerts.pop(rule_id, None)
        if occ:
            occ.resolved_at = datetime.now(timezone.utc)
            rule = self.rules.get(rule_id)
            logger.info("Alert rule resolved", extra={"alert_name": rule.name if rule else str(rule_id)})
        return occ


alert_engine = AlertEngine()
