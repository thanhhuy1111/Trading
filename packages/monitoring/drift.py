"""Phase 11: drift assessment. A documented, versioned relative-deviation threshold - not a
statistical test tuned to any backtest result (Section 2: "do not optimize toward profitable
backtest results in this task")."""

from decimal import Decimal
from typing import Optional

from packages.domain.entities import DriftAssessment
from packages.domain.enums import DriftSeverity

DRIFT_POLICY_VERSION = "drift_v1"
LOW_THRESHOLD = Decimal("0.10")
MODERATE_THRESHOLD = Decimal("0.25")
SEVERE_THRESHOLD = Decimal("0.50")

_RECOMMENDED_ACTION = {
    DriftSeverity.NONE: None,
    DriftSeverity.LOW: "MONITOR",
    DriftSeverity.MODERATE: "MARK_DEGRADED",
    DriftSeverity.SEVERE: "DISABLE_AND_REQUIRE_MANUAL_REVIEW",
}


class BaselineDriftService:
    def assess(
        self, subject: str, metric_name: str, baseline: Optional[Decimal], current: Optional[Decimal],
    ) -> DriftAssessment:
        if baseline is None or current is None:
            # Missing data is never silently treated as "no drift" (Section 4's
            # missing-state-is-conservative rule) - it is its own explicit, flagged case.
            return DriftAssessment(
                subject=subject, metric_name=metric_name, baseline_value=baseline, current_value=current,
                severity=DriftSeverity.NONE, reason_codes=["INSUFFICIENT_DATA_FOR_DRIFT_ASSESSMENT"],
                recommended_action="COLLECT_MORE_BASELINE_DATA",
            )

        deviation = _relative_deviation(baseline, current)
        severity = _severity_for(deviation)
        return DriftAssessment(
            subject=subject, metric_name=metric_name, baseline_value=baseline, current_value=current,
            severity=severity, reason_codes=[f"RELATIVE_DEVIATION:{deviation}", f"POLICY:{DRIFT_POLICY_VERSION}"],
            recommended_action=_RECOMMENDED_ACTION[severity],
        )


def _relative_deviation(baseline: Decimal, current: Decimal) -> Decimal:
    if baseline == 0:
        return abs(current)  # absolute fallback when the baseline itself is zero
    return abs(current - baseline) / abs(baseline)


def _severity_for(deviation: Decimal) -> DriftSeverity:
    if deviation >= SEVERE_THRESHOLD:
        return DriftSeverity.SEVERE
    if deviation >= MODERATE_THRESHOLD:
        return DriftSeverity.MODERATE
    if deviation >= LOW_THRESHOLD:
        return DriftSeverity.LOW
    return DriftSeverity.NONE
