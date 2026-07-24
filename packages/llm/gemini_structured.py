"""Gemini structured-output provider with bounded retry and fail-closed validation."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Awaitable, Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.llm.prompt_registry import PromptRegistry
from packages.llm.structured_provider import (
    LLMCallTelemetry,
    LLMProviderStatus,
    ProviderHealth,
    StructuredLLMRequest,
    StructuredLLMResult,
)

OutputT = TypeVar("OutputT", bound=BaseModel)
_SENSITIVE_VARIABLE_MARKERS = (
    "key",
    "secret",
    "token",
    "password",
    "balance",
    "credential",
    "private",
)


class GeminiStructuredSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    LLM_PROVIDER: str = "google"
    GEMINI_MODEL: str = ""
    GEMINI_API_KEY: str = Field(default="", exclude=True, repr=False)
    LLM_TEMPERATURE: float = Field(default=0.1, ge=0, le=2)
    LLM_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    LLM_TIMEOUT_SECONDS: float = Field(default=45.0, gt=0, le=300)
    LLM_STRUCTURED_OUTPUT: bool = True

    @property
    def is_configured(self) -> bool:
        return (
            self.LLM_PROVIDER == "google"
            and bool(self.GEMINI_MODEL)
            and bool(self.GEMINI_API_KEY)
            and self.LLM_STRUCTURED_OUTPUT
        )


class GeminiTransportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    requested_model_id: str
    served_model_version: Optional[str] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)


class GeminiRateLimitError(Exception):
    pass


class GeminiTransientError(Exception):
    pass


class GeminiTransport(Protocol):
    async def generate_json(
        self,
        *,
        model_id: str,
        prompt: str,
        response_schema: dict[str, object],
        temperature: float,
    ) -> GeminiTransportResponse: ...


class GoogleGenAITransport:
    """Thin SDK boundary. Construction and all tests are offline; client creation is lazy."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate_json(
        self,
        *,
        model_id: str,
        prompt: str,
        response_schema: dict[str, object],
        temperature: float,
    ) -> GeminiTransportResponse:
        from google.genai import types

        client = self._get_client()
        try:
            response = await client.aio.models.generate_content(  # type: ignore[attr-defined]
                model=model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=response_schema,
                    temperature=temperature,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc).upper()
            if "429" in message or "RESOURCE_EXHAUSTED" in message:
                raise GeminiRateLimitError from exc
            raise GeminiTransientError from exc
        text = response.text
        if not isinstance(text, str) or not text:
            raise GeminiTransientError
        usage = response.usage_metadata
        return GeminiTransportResponse(
            text=text,
            requested_model_id=model_id,
            served_model_version=getattr(response, "model_version", None),
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )


class GeminiStructuredProvider:
    def __init__(
        self,
        *,
        settings: GeminiStructuredSettings,
        prompts: PromptRegistry,
        transport: GeminiTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        retry_wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._prompts = prompts
        self._transport = transport
        self._monotonic = monotonic
        self._retry_wait = retry_wait

    def health(self) -> ProviderHealth:
        if not self._settings.is_configured:
            return ProviderHealth(
                status=LLMProviderStatus.NOT_CONFIGURED,
                provider="google",
                model_id=self._settings.GEMINI_MODEL or None,
                reason_codes=("LLM_PROVIDER_NOT_CONFIGURED",),
            )
        return ProviderHealth(
            status=LLMProviderStatus.CONFIGURED,
            provider="google",
            model_id=self._settings.GEMINI_MODEL,
        )

    async def generate(
        self,
        request: StructuredLLMRequest,
        output_model: type[OutputT],
    ) -> StructuredLLMResult[OutputT]:
        started = self._monotonic()
        prompt = self._prompts.get(request.prompt_name, request.prompt_version)
        if prompt is None:
            return self._result(
                request,
                LLMProviderStatus.ERROR,
                started,
                attempts=0,
                prompt_checksum="",
                reason="PROMPT_VERSION_NOT_FOUND",
            )
        try:
            if any(
                marker in variable.lower()
                for variable in request.variables
                for marker in _SENSITIVE_VARIABLE_MARKERS
            ):
                return self._result(
                    request,
                    LLMProviderStatus.ERROR,
                    started,
                    attempts=0,
                    prompt_checksum=prompt.checksum,
                    reason="SENSITIVE_PROMPT_VARIABLE_REJECTED",
                )
            rendered = prompt.render(request.variables)
        except (ValueError, KeyError, AttributeError, IndexError):
            return self._result(
                request,
                LLMProviderStatus.ERROR,
                started,
                attempts=0,
                prompt_checksum=prompt.checksum,
                reason="PROMPT_VARIABLES_MISMATCH",
            )
        if self._settings.GEMINI_API_KEY and (
            self._settings.GEMINI_API_KEY in rendered
            or "GEMINI_API_KEY=" in rendered.upper()
        ):
            return self._result(
                request,
                LLMProviderStatus.ERROR,
                started,
                attempts=0,
                prompt_checksum=prompt.checksum,
                reason="SENSITIVE_PROMPT_VALUE_REJECTED",
            )
        if not self._settings.is_configured:
            return self._result(
                request,
                LLMProviderStatus.NOT_CONFIGURED,
                started,
                attempts=0,
                prompt_checksum=prompt.checksum,
                reason="LLM_PROVIDER_NOT_CONFIGURED",
            )
        transport = self._transport or GoogleGenAITransport(
            self._settings.GEMINI_API_KEY
        )
        response_schema = output_model.model_json_schema()
        if not _schema_is_strict(response_schema):
            return self._result(
                request,
                LLMProviderStatus.ERROR,
                started,
                attempts=0,
                prompt_checksum=prompt.checksum,
                reason="LLM_OUTPUT_SCHEMA_NOT_STRICT",
            )
        attempts = 0
        for attempt in range(self._settings.LLM_MAX_RETRIES + 1):
            attempts += 1
            response: GeminiTransportResponse | None = None
            try:
                response = await asyncio.wait_for(
                    transport.generate_json(
                        model_id=self._settings.GEMINI_MODEL,
                        prompt=rendered,
                        response_schema=response_schema,
                        temperature=self._settings.LLM_TEMPERATURE,
                    ),
                    timeout=self._settings.LLM_TIMEOUT_SECONDS,
                )
                json.loads(
                    response.text,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_nonstandard_constant,
                )
                output = output_model.model_validate_json(
                    response.text,
                    strict=True,
                )
                if response.requested_model_id != self._settings.GEMINI_MODEL:
                    return self._result(
                        request,
                        LLMProviderStatus.ERROR,
                        started,
                        attempts=attempts,
                        prompt_checksum=prompt.checksum,
                        reason="LLM_REQUESTED_MODEL_ID_MISMATCH",
                        served_model_version=response.served_model_version,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                    )
                return self._result(
                    request,
                    LLMProviderStatus.SUCCESS,
                    started,
                    attempts=attempts,
                    prompt_checksum=prompt.checksum,
                    output=output,
                    served_model_version=response.served_model_version,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            except (ValidationError, json.JSONDecodeError, ValueError):
                return self._result(
                    request,
                    LLMProviderStatus.INVALID_OUTPUT,
                    started,
                    attempts=attempts,
                    prompt_checksum=prompt.checksum,
                    reason="LLM_STRUCTURED_OUTPUT_INVALID",
                    served_model_version=(
                        response.served_model_version if response else None
                    ),
                    input_tokens=response.input_tokens if response else None,
                    output_tokens=response.output_tokens if response else None,
                )
            except asyncio.TimeoutError:
                terminal_status = LLMProviderStatus.TIMEOUT
                reason = "LLM_PROVIDER_TIMEOUT"
            except GeminiRateLimitError:
                terminal_status = LLMProviderStatus.RATE_LIMITED
                reason = "LLM_PROVIDER_RATE_LIMITED"
            except GeminiTransientError:
                terminal_status = LLMProviderStatus.ERROR
                reason = "LLM_PROVIDER_TRANSIENT_ERROR"
            except Exception:  # noqa: BLE001
                terminal_status = LLMProviderStatus.ERROR
                reason = "LLM_PROVIDER_ERROR"
            if attempt < self._settings.LLM_MAX_RETRIES:
                await self._retry_wait(0.5 * (attempt + 1))
                continue
            return self._result(
                request,
                terminal_status,
                started,
                attempts=attempts,
                prompt_checksum=prompt.checksum,
                reason=reason,
            )
        raise AssertionError("bounded retry loop must return")

    def _result(
        self,
        request: StructuredLLMRequest,
        status: LLMProviderStatus,
        started: float,
        *,
        attempts: int,
        prompt_checksum: str,
        output: OutputT | None = None,
        served_model_version: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        reason: str | None = None,
    ) -> StructuredLLMResult[OutputT]:
        return StructuredLLMResult[OutputT](
            status=status,
            output=output,
            telemetry=LLMCallTelemetry(
                request_id=request.request_id,
                provider="google",
                model_id=self._settings.GEMINI_MODEL,
                served_model_version=served_model_version,
                prompt_name=request.prompt_name,
                prompt_version=request.prompt_version,
                prompt_checksum=prompt_checksum,
                attempts=attempts,
                latency_ms=max(0.0, (self._monotonic() - started) * 1000),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            reason_codes=((reason,) if reason else ()),
        )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def _schema_is_strict(schema: object) -> bool:
    if isinstance(schema, dict):
        if schema.get("type") == "object" and schema.get("additionalProperties") is not False:
            return False
        return all(_schema_is_strict(value) for value in schema.values())
    if isinstance(schema, list):
        return all(_schema_is_strict(value) for value in schema)
    return True
