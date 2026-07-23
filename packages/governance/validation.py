from decimal import Decimal
from typing import Any, Dict, Optional

from packages.telemetry.redaction import redactor


class InputValidator:
    """Centralized input validation and boundary enforcement."""

    @staticmethod
    def validate_decimal_amount(
        value: Decimal, allow_zero: bool = True, max_value: Optional[Decimal] = None
    ) -> Decimal:
        if value.is_nan() or value.is_infinite():
            raise ValueError("VALIDATION_ERROR: Value cannot be NaN or Infinity")
        if not allow_zero and value <= Decimal("0.0"):
            raise ValueError("VALIDATION_ERROR: Value must be strictly positive")
        if allow_zero and value < Decimal("0.0"):
            raise ValueError("VALIDATION_ERROR: Value cannot be negative")
        if max_value is not None and value > max_value:
            raise ValueError(f"VALIDATION_ERROR: Value {value} exceeds maximum allowed cap {max_value}")
        return value

    @staticmethod
    def validate_payload_size(data: bytes, max_bytes: int = 1_048_576) -> None:
        if len(data) > max_bytes:
            raise ValueError(f"VALIDATION_ERROR: Payload size {len(data)} exceeds maximum limit {max_bytes} bytes")


class OutputSanitizer:
    """Ensures responses never expose stack traces, secrets, database DSNs, or internal keys."""

    @staticmethod
    def sanitize_response_dto(data: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = redactor.redact_dict(data)
        # Remove traceback or exception details
        cleaned.pop("traceback", None)
        cleaned.pop("exception_raw", None)
        return cleaned


input_validator = InputValidator()
output_sanitizer = OutputSanitizer()
