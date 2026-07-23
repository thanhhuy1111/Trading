from datetime import datetime
from decimal import Decimal

from packages.agents.models import AgentSignal
from packages.governance.models import SignalValidationResult


class SignalValidationGate:
    """Validates incoming Strategy Agent signals prior to Critic Agent scrutiny."""

    def validate_signal(self, signal: AgentSignal, current_time: datetime) -> SignalValidationResult:
        rejections = []
        warnings = []

        # Check expiration
        if signal.expires_at <= current_time:
            rejections.append("SIGNAL_EXPIRED")

        # Check generated timestamp
        if signal.generated_at > current_time:
            rejections.append("FUTURE_GENERATED_TIMESTAMP")

        # Check reference price
        if signal.reference_price <= Decimal("0"):
            rejections.append("INVALID_REFERENCE_PRICE")

        # Check confidence range
        if not (Decimal("0.0") <= signal.confidence <= Decimal("1.0")):
            rejections.append("INVALID_CONFIDENCE_RANGE")

        # Check horizon
        if signal.horizon_minutes <= 0:
            rejections.append("INVALID_HORIZON_MINUTES")

        is_valid = len(rejections) == 0
        return SignalValidationResult(
            valid=is_valid,
            signal_id=signal.signal_id,
            rejection_codes=rejections,
            warnings=warnings,
            validated_at=current_time,
            validator_version="1.0.0"
        )


signal_validation_gate = SignalValidationGate()
