"""Grounded Gemini market-context agents.

Each logical specialist receives an independent prompt and Google Search call. A response is
usable only when it is strict schema-valid *and* the Gemini Interaction contains URL citation
annotations. Source IDs come exclusively from those annotations, never from model-authored
JSON. The output is advisory research context: ``risk_adjustment`` is always forced to zero
and no execution/risk authority is exposed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Literal, Protocol, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.chat_agent.config import GeminiSettings
from packages.domain.entities import MarketContextAssessment
from packages.domain.enums import MarketContextStatus
from packages.llm.framework import detect_prompt_injection

ContextRole = Literal["news", "macro", "sentiment", "risk_critic"]


class GroundedContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stance: Literal["BULLISH", "NEUTRAL", "BEARISH"]
    summary: str = Field(min_length=1, max_length=1600)
    confidence: float = Field(ge=0, le=1)
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    limitations: tuple[str, ...] = Field(default=(), max_length=8)


class GroundedTransportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    citation_urls: tuple[str, ...]
    served_model_version: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class GroundedRateLimitError(Exception):
    pass


class GroundedTransportError(Exception):
    pass


class GroundedContextTransport(Protocol):
    async def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        response_schema: dict[str, object],
        timeout_seconds: float,
    ) -> GroundedTransportResponse: ...


class GoogleGroundedContextTransport:
    """Interactions API boundary for structured output plus Google Search grounding."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        response_schema: dict[str, object],
        timeout_seconds: float,
    ) -> GroundedTransportResponse:
        client = self._get_client()
        try:
            interaction = await client.aio.interactions.create(  # type: ignore[attr-defined]
                model=model_id,
                input=prompt,
                tools=[{"type": "google_search"}],
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema,
                },
                store=False,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - mapped to bounded fail-closed status
            marker = str(exc).upper()
            if "429" in marker or "RATE_LIMIT" in marker or "QUOTA" in marker or "RESOURCE_EXHAUSTED" in marker:
                raise GroundedRateLimitError from exc
            raise GroundedTransportError from exc

        text = getattr(interaction, "output_text", None)
        if not isinstance(text, str) or not text:
            raise GroundedTransportError
        citation_urls = _citation_urls_from_steps(
            getattr(interaction, "steps", None) or ()
        )
        usage = getattr(interaction, "usage", None)
        model = getattr(interaction, "model", None)
        served_model = (
            getattr(model, "version", None)
            or getattr(model, "name", None)
            or str(model or "")
            or None
        )
        return GroundedTransportResponse(
            text=text,
            citation_urls=citation_urls,
            served_model_version=served_model,
            input_tokens=_usage_value(
                usage,
                "total_input_tokens",
                "input_tokens",
                "prompt_token_count",
            ),
            output_tokens=_usage_value(
                usage,
                "total_output_tokens",
                "output_tokens",
                "candidates_token_count",
            ),
        )


def _usage_value(usage: object, *names: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _citation_urls_from_steps(steps: Sequence[object]) -> tuple[str, ...]:
    urls: list[str] = []
    for step in steps:
        if getattr(step, "type", None) != "model_output":
            continue
        for content in getattr(step, "content", None) or ():
            if getattr(content, "type", None) != "text":
                continue
            for annotation in getattr(content, "annotations", None) or ():
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                url = getattr(annotation, "url", None)
                if isinstance(url, str) and _is_public_http_url(url):
                    urls.append(url)
    return tuple(dict.fromkeys(urls))


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith((".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        return True


_ROLE_INSTRUCTIONS: dict[ContextRole, str] = {
    "news": (
        "Search for material, attributable BTC/ETH market news published in the previous "
        "twenty-four hours. Separate confirmed reporting from speculation."
    ),
    "macro": (
        "Search for current macroeconomic facts that may affect crypto: rates, inflation, "
        "liquidity, dollar conditions and scheduled policy events. Use primary sources when available."
    ),
    "sentiment": (
        "Search public, attributable indicators of current crypto market sentiment and positioning. "
        "Do not infer sentiment from a single anonymous post."
    ),
    "risk_critic": (
        "Act as an adversarial market-risk critic. Search for current operational, regulatory, "
        "liquidity and event risks that could invalidate a research thesis."
    ),
}


class GroundedGeminiContextAgent:
    def __init__(
        self,
        *,
        role: ContextRole,
        settings: GeminiSettings,
        transport: GroundedContextTransport | None = None,
        retry_wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.role = role
        self.agent_name = f"{role}_agent"
        self.agent_version = "grounded_v1"
        self._settings = settings
        self._transport = transport
        self._retry_wait = retry_wait
        self._clock = clock

    async def assess(
        self,
        symbol: str,
        as_of_time: datetime,
    ) -> MarketContextAssessment:
        if as_of_time.tzinfo is None:
            return self._unavailable(as_of_time, "ANALYSIS_TIMESTAMP_INVALID")
        if not self._settings.is_configured or not self._settings.GEMINI_CONTEXT_ENABLED:
            return self._unavailable(as_of_time, "LLM_PROVIDER_NOT_CONFIGURED")

        prompt = (
            "You are the independent "
            f"{self.role} specialist in a research-only crypto analysis system. "
            f"Analysis symbol: {symbol}. Analysis time: {as_of_time.isoformat()}. "
            f"{_ROLE_INSTRUCTIONS[self.role]} "
            "Use Google Search and base every factual claim on cited public sources. "
            "Return a cautious classification, not a trade instruction. Confidence is a subjective "
            "heuristic score, not a calibrated probability. Never claim certainty, never mention or "
            "request credentials, balances, private APIs, orders or live execution."
        )
        transport = self._transport or GoogleGroundedContextTransport(
            self._settings.GEMINI_API_KEY
        )
        attempts = self._settings.GEMINI_CONTEXT_MAX_RETRIES + 1
        terminal_reason = "LLM_PROVIDER_CALL_FAILED"
        for attempt in range(attempts):
            try:
                response = await asyncio.wait_for(
                    transport.generate(
                        model_id=self._settings.GEMINI_MODEL,
                        prompt=prompt,
                        response_schema=GroundedContextOutput.model_json_schema(),
                        timeout_seconds=self._settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                    ),
                    timeout=self._settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                )
                output = _validate_output(response.text)
                sources = tuple(
                    source
                    for source in response.citation_urls
                    if _is_public_http_url(source)
                )[: self._settings.GEMINI_CONTEXT_MAX_SOURCES]
                if not sources:
                    return self._unavailable(
                        as_of_time,
                        "GROUNDING_CITATIONS_MISSING",
                    )
                retrieved_at = self._clock()
                if retrieved_at.tzinfo is None or retrieved_at < as_of_time:
                    return self._unavailable(
                        as_of_time,
                        "GROUNDING_RETRIEVAL_TIMESTAMP_INVALID",
                    )
                return MarketContextAssessment(
                    agent_name=self.agent_name,
                    agent_version=self.agent_version,
                    analysis_timestamp=retrieved_at,
                    decision_timestamp=as_of_time,
                    source_ids=list(sources),
                    source_timestamps=[retrieved_at for _ in sources],
                    view=f"{output.stance}: {output.summary}",
                    confidence=Decimal(str(output.confidence)),
                    risk_level=output.risk_level,
                    risk_adjustment=Decimal("0"),
                    status=MarketContextStatus.AVAILABLE,
                    reason_codes=["GOOGLE_SEARCH_GROUNDED"],
                    limitations=[
                        "LLM_CONFIDENCE_IS_HEURISTIC_NOT_CALIBRATED_PROBABILITY",
                        "SOURCE_TIMESTAMP_IS_RETRIEVAL_TIME",
                        f"MODEL_ID:{response.served_model_version or self._settings.GEMINI_MODEL}",
                        *output.limitations,
                    ],
                )
            except asyncio.TimeoutError:
                terminal_reason = "LLM_PROVIDER_TIMEOUT"
            except GroundedRateLimitError:
                terminal_reason = "LLM_PROVIDER_RATE_LIMITED"
            except (GroundedTransportError, ValidationError, ValueError, json.JSONDecodeError):
                terminal_reason = "LLM_PROVIDER_INVALID_OR_UNAVAILABLE"
            if attempt + 1 < attempts:
                await self._retry_wait(0.5 * (attempt + 1))
        return self._unavailable(as_of_time, terminal_reason)

    def _unavailable(
        self,
        as_of_time: datetime,
        reason: str,
    ) -> MarketContextAssessment:
        return MarketContextAssessment(
            agent_name=self.agent_name,
            agent_version=self.agent_version,
            analysis_timestamp=as_of_time,
            decision_timestamp=as_of_time if as_of_time.tzinfo is not None else None,
            source_ids=[],
            source_timestamps=[],
            view=None,
            confidence=None,
            risk_level=None,
            risk_adjustment=Decimal("0"),
            status=MarketContextStatus.NOT_AVAILABLE,
            reason_codes=[reason],
            limitations=["No grounded specialist output was admitted."],
        )


def _validate_output(text: str) -> GroundedContextOutput:
    json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonstandard_constant,
    )
    output = GroundedContextOutput.model_validate_json(text, strict=True)
    free_text = " ".join((output.summary, *output.limitations))
    if detect_prompt_injection(free_text):
        raise ValueError("grounded output contains prompt-injection markers")
    lowered = free_text.lower()
    if any(
        marker in lowered
        for marker in (
            "api key",
            "api secret",
            "private key",
            "place the order",
            "enable live trading",
            "go all in",
        )
    ):
        raise ValueError("grounded output contains prohibited instructions")
    return output


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


@dataclass(frozen=True)
class GroundedMarketContextService:
    agents: tuple[GroundedGeminiContextAgent, ...]

    @classmethod
    def from_settings(
        cls,
        settings: GeminiSettings,
        *,
        transports: dict[ContextRole, GroundedContextTransport] | None = None,
    ) -> GroundedMarketContextService:
        roles: tuple[ContextRole, ...] = (
            "news",
            "macro",
            "sentiment",
            "risk_critic",
        )
        return cls(
            agents=tuple(
                GroundedGeminiContextAgent(
                    role=role,
                    settings=settings,
                    transport=(transports or {}).get(role),
                )
                for role in roles
            )
        )

    async def assess(
        self,
        symbol: str,
        as_of_time: datetime,
    ) -> list[MarketContextAssessment]:
        return list(
            await asyncio.gather(
                *(agent.assess(symbol, as_of_time) for agent in self.agents)
            )
        )
