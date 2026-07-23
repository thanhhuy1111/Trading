from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.telemetry.models import SloDefinition, SloMeasurement


class SloService:
    """Manages versioned Service Level Objectives (SLO) and Error Budget calculations."""

    def __init__(self) -> None:
        self.definitions: Dict[UUID, SloDefinition] = {}
        self.measurements: Dict[UUID, List[SloMeasurement]] = {}
        self._init_default_slos()

    def _init_default_slos(self) -> None:
        defaults = [
            SloDefinition(
                name="Market Data Freshness",
                description="Percentage of public market events received within 1000ms threshold",
                target_percentage=Decimal("99.90"),
                window_days=30
            ),
            SloDefinition(
                name="Pipeline Execution Success",
                description="Percentage of closed candles successfully evaluated without unhandled exceptions",
                target_percentage=Decimal("99.50"),
                window_days=30
            ),
            SloDefinition(
                name="Accounting Integrity",
                description="Percentage of portfolio reconciliation audits passing 16 completeness checks",
                target_percentage=Decimal("100.00"),
                window_days=30
            ),
        ]
        for slo in defaults:
            self.definitions[slo.slo_id] = slo
            self.measurements[slo.slo_id] = []

    def evaluate_slo(self, slo_id: UUID, current_val_pct: Decimal) -> SloMeasurement:
        slo = self.definitions.get(slo_id)
        if not slo:
            raise ValueError(f"SLO_ERROR: Definition {slo_id} not found")

        # Error budget remaining = 100 - ((target - current) / (100 - target) * 100) if degraded
        target = slo.target_percentage
        err_budget = Decimal("100.00")
        if current_val_pct < target:
            shortfall = target - current_val_pct
            allowed_loss = Decimal("100.00") - target
            if allowed_loss > Decimal("0.0"):
                err_budget = max(Decimal("0.0"), Decimal("100.00") - (shortfall / allowed_loss * Decimal("100.00")))
            else:
                err_budget = Decimal("0.0")

        measurement = SloMeasurement(
            measurement_id=uuid4(),
            slo_id=slo_id,
            current_value_pct=current_val_pct,
            error_budget_remaining_pct=err_budget,
            evaluated_at=datetime.now(timezone.utc)
        )

        self.measurements[slo_id].append(measurement)
        logger.info(
            "SLO evaluated",
            extra={"slo_name": slo.name, "current_pct": str(current_val_pct), "budget_remaining": str(err_budget)}
        )
        return measurement


slo_service = SloService()
