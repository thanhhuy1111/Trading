"""Explicit error types for service ports (Phase 2). Every service raises one of these
(or a subclass) instead of a bare Exception, so callers — especially the recommendation
runtime — can pattern-match on failure kind and map it to a safe ApplicationResultState
instead of leaking an unhandled traceback (Section 4, rule 14: "no silent exception
swallowing" — this is the flip side: errors must be typed and visible, not swallowed OR
generic)."""


class PortError(Exception):
    """Base class for all service-port errors."""

    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class DataUnavailableError(PortError):
    """Requested data (market data, evidence, correlation, ...) does not exist."""


class DataQualityError(PortError):
    """Data exists but failed validation (bad OHLC, severe gaps, stale)."""


class ModelUnavailableError(PortError):
    """No usable model/artifact for the requested (symbol, timeframe, version)."""


class EvidenceMismatchError(PortError):
    """An evidence lookup found a record but the key didn't exact-match."""


class RiskLimitExceededError(PortError):
    """Portfolio risk governor rejected or reduced a candidate."""


class TimeoutPortError(PortError):
    """An external-dependency call (LLM, network) exceeded its timeout policy."""


class ProviderUnavailableError(PortError):
    """An external provider (LLM, exchange data) is disabled or unreachable."""


class InvalidResponseError(PortError):
    """An external provider responded, but the response failed schema validation."""
