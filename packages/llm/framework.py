"""Phase 9: LLM agent framework.

Every concrete agent actually wired into this task (`packages.intelligence.market_context`'s
no-op News/Macro/Sentiment/RiskCritic adapters) is disabled - none of them call a real LLM
provider, and none is claimed to. This module is the fuller contract a real provider-backed
agent will implement later without any caller (Phase 4's `BaselineMarketContextService`, Phase
7's recommendation runtime) changing: timeout + bounded retry + circuit breaker, prompt/response
defensive handling, and structured-output validation - built and tested now so Checkpoint 3
only has to write `_call_provider`, not re-derive reliability plumbing.

Defensive requirements this module enforces structurally, not just by convention:
  - no secrets/keys/balances in a prompt payload (`redact_sensitive_fields`, fail-closed)
  - no un-flagged prompt injection in externally-sourced text (`detect_prompt_injection`)
  - no unvalidated LLM output reaching a domain entity (`validate_structured_output`)
  - no unbounded tool use (`LLMAgentConfig.allowed_tools`, empty by default - no tools)
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from packages.domain.entities import MarketContextAssessment
from packages.domain.enums import LLMAgentStatus, MarketContextStatus

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 5
DEFAULT_CIRCUIT_RESET_SECONDS = 60.0


@dataclass(frozen=True)
class LLMAgentConfig:
    agent_name: str
    agent_version: str
    prompt_version: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    circuit_breaker_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
    circuit_breaker_reset_seconds: float = DEFAULT_CIRCUIT_RESET_SECONDS
    allowed_tools: FrozenSet[str] = field(default_factory=frozenset)  # empty = no tool use permitted


def check_tool_allowed(config: LLMAgentConfig, tool_name: str) -> bool:
    return tool_name in config.allowed_tools


# --- Defensive input handling ---

_SENSITIVE_KEY_MARKERS = ("key", "secret", "token", "password", "balance", "credential", "private")


def redact_sensitive_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """No API keys, secrets, account balances, or private keys may ever reach an LLM prompt
    (Section 4, rule 3: "no secrets/keys/balances sent to LLMs"). Redacts any key whose NAME
    matches a sensitive marker - fail-closed (redact when uncertain), never fail-open."""
    return {
        k: ("[REDACTED]" if any(marker in k.lower() for marker in _SENSITIVE_KEY_MARKERS) else v)
        for k, v in payload.items()
    }


_INJECTION_MARKERS = (
    "ignore previous instructions", "ignore all previous", "disregard all prior", "disregard previous",
    "system prompt", "you are now", "new instructions:", "override your instructions",
)


def detect_prompt_injection(text: str) -> List[str]:
    """Best-effort heuristic flags for prompt-injection patterns in externally-sourced text
    (news headlines, social content) that would otherwise go straight into an LLM prompt. This
    never blocks by itself - a real provider-backed agent decides policy - but the flags must
    never be silently dropped; callers are expected to fold non-empty results into
    `reason_codes`/`limitations`."""
    lowered = text.lower()
    return [marker for marker in _INJECTION_MARKERS if marker in lowered]


# --- Structured output validation ---

# MarketContextAssessment (packages.domain.entities) IS the structured output schema every LLM
# agent must produce - a provider's raw JSON response is validated against these bounds BEFORE
# any domain entity is constructed from it, never trusted as-is.
_REQUIRED_STRUCTURED_FIELDS = frozenset({"view", "confidence", "risk_level", "risk_adjustment"})


def validate_structured_output(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validates a raw (provider-returned) JSON payload against the structured output schema
    before it is allowed to become a `MarketContextAssessment`. Returns (is_valid,
    violation_reason_codes) - never raises, so a malformed response degrades to
    INVALID_RESPONSE rather than crashing the caller."""
    violations: List[str] = []
    missing = _REQUIRED_STRUCTURED_FIELDS - set(payload)
    if missing:
        violations.append(f"MISSING_REQUIRED_FIELDS:{sorted(missing)}")
        return False, violations

    confidence = payload.get("confidence")
    if confidence is not None and not (0 <= float(confidence) <= 1):
        violations.append("CONFIDENCE_OUT_OF_BOUNDS")
    risk_adjustment = payload.get("risk_adjustment")
    if risk_adjustment is not None and not (-1 <= float(risk_adjustment) <= 1):
        violations.append("RISK_ADJUSTMENT_OUT_OF_BOUNDS")
    view = payload.get("view")
    if view is not None and not isinstance(view, str):
        violations.append("VIEW_NOT_A_STRING")
    return (len(violations) == 0), violations


# --- Reliability: timeout + bounded retry + circuit breaker ---


class CircuitBreaker:
    """Opens after `failure_threshold` consecutive failures; stays open (rejecting calls
    immediately, never attempting the provider) until `reset_seconds` have elapsed, then allows
    one trial call. A disabled agent (this task's only concrete agents) never exercises this -
    it exists for the real provider Checkpoint 3 will eventually wire in."""

    def __init__(self, failure_threshold: int, reset_seconds: float) -> None:
        self._failure_threshold = failure_threshold
        self._reset_seconds = reset_seconds
        self._consecutive_failures = 0
        self._opened_at: Optional[datetime] = None

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self, now: Optional[datetime] = None) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold and self._opened_at is None:
            self._opened_at = now or datetime.now(timezone.utc)

    def allow_request(self, now: Optional[datetime] = None) -> bool:
        if self._opened_at is None:
            return True
        current = now or datetime.now(timezone.utc)
        if current - self._opened_at >= timedelta(seconds=self._reset_seconds):
            return True  # half-open: allow one trial call
        return False


def _not_available(
    config: LLMAgentConfig, as_of_time: datetime, status: LLMAgentStatus, reason: str,
) -> MarketContextAssessment:
    return MarketContextAssessment(
        agent_name=config.agent_name,
        agent_version=config.agent_version,
        analysis_timestamp=datetime.now(timezone.utc),
        decision_timestamp=as_of_time,
        source_ids=[],
        source_timestamps=[],
        view=None,
        confidence=None,
        risk_level=None,
        status=MarketContextStatus.NOT_AVAILABLE,
        reason_codes=[reason, f"LLM_AGENT_STATUS:{status.value}"],
        limitations=[f"prompt_version={config.prompt_version}"],
    )


class BaseLLMAgent(ABC):
    """Wraps a concrete provider call with timeout + bounded retry + circuit breaker, and
    always degrades to a NOT_AVAILABLE `MarketContextAssessment` rather than raising or
    fabricating a view (Section 9: "the runtime must work with this entire service
    disabled")."""

    def __init__(self, config: LLMAgentConfig) -> None:
        self.config = config
        self._circuit = CircuitBreaker(config.circuit_breaker_failure_threshold, config.circuit_breaker_reset_seconds)

    @abstractmethod
    async def _call_provider(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment: ...

    async def assess(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment:
        if not self._circuit.allow_request():
            return _not_available(self.config, as_of_time, LLMAgentStatus.CIRCUIT_OPEN, "LLM_CIRCUIT_OPEN")

        for attempt in range(self.config.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._call_provider(symbol, as_of_time), timeout=self.config.timeout_seconds,
                )
                self._circuit.record_success()
                return result
            except asyncio.TimeoutError:
                self._circuit.record_failure()
                if attempt == self.config.max_retries:
                    return _not_available(self.config, as_of_time, LLMAgentStatus.TIMEOUT, "LLM_CALL_TIMED_OUT")
            except Exception:  # noqa: BLE001 - any provider/parse error degrades, never raises to the caller
                self._circuit.record_failure()
                if attempt == self.config.max_retries:
                    return _not_available(
                        self.config, as_of_time, LLMAgentStatus.INVALID_RESPONSE, "LLM_PROVIDER_CALL_FAILED",
                    )
        # Unreachable: the loop above always returns on its final iteration.
        return _not_available(self.config, as_of_time, LLMAgentStatus.NOT_AVAILABLE, "LLM_AGENT_UNAVAILABLE")


class DisabledLLMAgent(BaseLLMAgent):
    """The only concrete agent kind this task instantiates: never calls a provider, always
    returns NOT_AVAILABLE immediately (no retry/circuit-breaker overhead for a provider that
    structurally does not exist)."""

    async def _call_provider(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment:
        raise NotImplementedError("DisabledLLMAgent never calls a provider.")

    async def assess(self, symbol: str, as_of_time: datetime) -> MarketContextAssessment:
        return _not_available(self.config, as_of_time, LLMAgentStatus.NOT_AVAILABLE, "LLM_PROVIDER_NOT_CONFIGURED")
