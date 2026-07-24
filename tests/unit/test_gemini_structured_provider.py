"""Offline Phase 5 tests for Gemini structured output, retries, telemetry and prompts."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.chat_agent.config import GeminiSettings
from packages.common.immutable import FrozenMapping
from packages.llm.gemini_structured import (
    GeminiRateLimitError,
    GeminiStructuredProvider,
    GeminiStructuredSettings,
    GeminiTransientError,
    GeminiTransportResponse,
)
from packages.llm.prompt_registry import PromptDefinition, PromptRegistry
from packages.llm.structured_provider import (
    LLMProviderStatus,
    StructuredLLMRequest,
)


class Interpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stance: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]


def _registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.register(
        PromptDefinition(
            name="technical_interpretation",
            version="1.0.0",
            template="Interpret {evidence_json} without inventing numeric claims.",
            required_variables=("evidence_json",),
        )
    )
    return registry


def _request(**variables: str) -> StructuredLLMRequest:
    return StructuredLLMRequest(
        request_id="analysis-001:technical",
        prompt_name="technical_interpretation",
        prompt_version="1.0.0",
        variables=FrozenMapping(
            variables or {"evidence_json": '{"rsi": 55, "evidence_id": "ev-1"}'}
        ),
    )


def _settings(**updates: object) -> GeminiStructuredSettings:
    payload: dict[str, object] = {
        "LLM_PROVIDER": "google",
        "GEMINI_MODEL": "configured-test-model",
        "GEMINI_API_KEY": "test-key-never-sent-in-prompt",
        "LLM_TEMPERATURE": 0.1,
        "LLM_MAX_RETRIES": 2,
        "LLM_TIMEOUT_SECONDS": 0.1,
        "LLM_STRUCTURED_OUTPUT": True,
    }
    payload.update(updates)
    return GeminiStructuredSettings.model_validate(payload)


class ScriptedTransport:
    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    async def generate_json(self, **kwargs: object) -> GeminiTransportResponse:
        self.calls.append(dict(kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, GeminiTransportResponse)
        return item


def _valid_response() -> GeminiTransportResponse:
    return GeminiTransportResponse(
        text='{"stance":"BULLISH","confidence":0.7,"evidence_ids":["ev-1"]}',
        requested_model_id="configured-test-model",
        served_model_version="configured-test-model-20260724",
        input_tokens=23,
        output_tokens=11,
    )


def test_prompt_registry_is_exact_append_only_and_requires_all_variables() -> None:
    registry = _registry()
    prompt = registry.get("technical_interpretation", "1.0.0")
    assert prompt is not None
    assert len(prompt.checksum) == 64
    assert "ev-1" in prompt.render({"evidence_json": "ev-1"})
    assert registry.get("technical_interpretation", "latest") is None
    with pytest.raises(ValueError, match="PROMPT_VERSION_EXISTS"):
        registry.register(prompt)
    with pytest.raises(ValueError, match="PROMPT_VARIABLES_MISMATCH"):
        prompt.render({})
    for invalid_template in (
        "bad {evidence_json.value}",
        "bad {evidence_json[0]}",
        "bad {evidence_json!r}",
        "bad {evidence_json:{width}}",
    ):
        with pytest.raises(
            ValueError,
            match="prompt placeholders must be simple identifiers",
        ):
            PromptDefinition(
                name="invalid",
                version="1",
                template=invalid_template,
                required_variables=("evidence_json",),
            )


def test_api_key_is_excluded_from_settings_repr_and_serialization() -> None:
    settings = _settings()
    assert "test-key-never-sent-in-prompt" not in repr(settings)
    assert "GEMINI_API_KEY" not in settings.model_dump()


async def test_missing_configuration_is_safe_and_never_calls_transport() -> None:
    transport = ScriptedTransport([_valid_response()])
    settings = GeminiStructuredSettings(
        GEMINI_MODEL="",
        GEMINI_API_KEY="",
    )
    provider = GeminiStructuredProvider(
        settings=settings,
        prompts=_registry(),
        transport=transport,
    )
    assert provider.health().status == LLMProviderStatus.NOT_CONFIGURED
    result = await provider.generate(_request(), Interpretation)
    assert result.status == LLMProviderStatus.NOT_CONFIGURED
    assert result.output is None
    assert result.reason_codes == ("LLM_PROVIDER_NOT_CONFIGURED",)
    assert result.telemetry.attempts == 0
    assert transport.calls == []


async def test_valid_structured_output_records_versions_tokens_and_latency() -> None:
    transport = ScriptedTransport([_valid_response()])
    provider = GeminiStructuredProvider(
        settings=_settings(),
        prompts=_registry(),
        transport=transport,
        monotonic=lambda: 10.0,
    )
    assert provider.health().status == LLMProviderStatus.CONFIGURED
    result = await provider.generate(_request(), Interpretation)

    assert result.status == LLMProviderStatus.SUCCESS
    assert result.output == Interpretation(
        stance="BULLISH",
        confidence=0.7,
        evidence_ids=("ev-1",),
    )
    assert result.telemetry.model_id == "configured-test-model"
    assert result.telemetry.served_model_version == "configured-test-model-20260724"
    assert result.telemetry.prompt_version == "1.0.0"
    assert result.telemetry.input_tokens == 23
    assert result.telemetry.output_tokens == 11
    assert result.telemetry.attempts == 1
    assert transport.calls[0]["temperature"] == 0.1
    assert "test-key" not in str(transport.calls)
    schema = transport.calls[0]["response_schema"]
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False


async def test_requested_model_mismatch_fails_but_preserves_served_usage() -> None:
    transport = ScriptedTransport(
        [
            GeminiTransportResponse(
                text='{"stance":"BULLISH","confidence":0.7,"evidence_ids":["ev-1"]}',
                requested_model_id="unexpected-request-model",
                served_model_version="served-version-123",
                input_tokens=17,
                output_tokens=8,
            )
        ]
    )
    result = await GeminiStructuredProvider(
        settings=_settings(),
        prompts=_registry(),
        transport=transport,
    ).generate(_request(), Interpretation)
    assert result.status == LLMProviderStatus.ERROR
    assert result.output is None
    assert result.reason_codes == ("LLM_REQUESTED_MODEL_ID_MISMATCH",)
    assert result.telemetry.model_id == "configured-test-model"
    assert result.telemetry.served_model_version == "served-version-123"
    assert result.telemetry.input_tokens == 17
    assert result.telemetry.output_tokens == 8


async def test_invalid_json_or_semantics_fail_closed_without_retry() -> None:
    for text in (
        "not-json",
        '{"stance":"BEARISH","stance":"BULLISH","confidence":0.7,"evidence_ids":["ev-1"]}',
        '{"stance":"BULLISH","confidence":"0.7","evidence_ids":["ev-1"]}',
        '{"stance":"BULLISH","confidence":NaN,"evidence_ids":["ev-1"]}',
        '{"stance":"BULLISH","confidence":4,"evidence_ids":["ev-1"]}',
        '{"stance":"BULLISH","confidence":0.7,"evidence_ids":["ev-1"],"extra":1}',
    ):
        transport = ScriptedTransport(
            [
                GeminiTransportResponse(
                    text=text,
                    requested_model_id="configured-test-model",
                    served_model_version="served-invalid-output",
                    input_tokens=9,
                    output_tokens=4,
                )
            ]
        )
        result = await GeminiStructuredProvider(
            settings=_settings(),
            prompts=_registry(),
            transport=transport,
        ).generate(_request(), Interpretation)
        assert result.status == LLMProviderStatus.INVALID_OUTPUT
        assert result.output is None
        assert result.reason_codes == ("LLM_STRUCTURED_OUTPUT_INVALID",)
        assert result.telemetry.attempts == 1
        assert result.telemetry.served_model_version == "served-invalid-output"
        assert result.telemetry.input_tokens == 9
        assert result.telemetry.output_tokens == 4
        assert len(transport.calls) == 1

    class PermissiveOutput(BaseModel):
        stance: str

    permissive_transport = ScriptedTransport(
        [
            GeminiTransportResponse(
                text='{"stance":"BULLISH","hallucinated":1}',
                requested_model_id="configured-test-model",
            )
        ]
    )
    permissive = await GeminiStructuredProvider(
        settings=_settings(),
        prompts=_registry(),
        transport=permissive_transport,
    ).generate(_request(), PermissiveOutput)
    assert permissive.reason_codes == ("LLM_OUTPUT_SCHEMA_NOT_STRICT",)
    assert permissive_transport.calls == []


async def test_rate_limit_retries_are_bounded_and_preserve_identical_request() -> None:
    transport = ScriptedTransport(
        [
            GeminiRateLimitError(),
            GeminiRateLimitError(),
            _valid_response(),
        ]
    )
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    result = await GeminiStructuredProvider(
        settings=_settings(),
        prompts=_registry(),
        transport=transport,
        retry_wait=record_wait,
    ).generate(_request(), Interpretation)
    assert result.status == LLMProviderStatus.SUCCESS
    assert result.telemetry.attempts == 3
    assert waits == [0.5, 1.0]
    assert transport.calls[0] == transport.calls[1] == transport.calls[2]


async def test_timeout_and_provider_errors_never_escape_and_retry_is_bounded() -> None:
    class SlowTransport:
        calls = 0

        async def generate_json(self, **kwargs: object) -> GeminiTransportResponse:
            self.calls += 1
            await asyncio.sleep(1)
            return _valid_response()

    slow = SlowTransport()
    timeout_result = await GeminiStructuredProvider(
        settings=_settings(LLM_MAX_RETRIES=1, LLM_TIMEOUT_SECONDS=0.001),
        prompts=_registry(),
        transport=slow,
        retry_wait=lambda _: asyncio.sleep(0),
    ).generate(_request(), Interpretation)
    assert timeout_result.status == LLMProviderStatus.TIMEOUT
    assert timeout_result.output is None
    assert timeout_result.telemetry.attempts == 2
    assert slow.calls == 2

    failing = ScriptedTransport(
        [GeminiTransientError(), GeminiTransientError()]
    )
    error_result = await GeminiStructuredProvider(
        settings=_settings(LLM_MAX_RETRIES=1),
        prompts=_registry(),
        transport=failing,
        retry_wait=lambda _: asyncio.sleep(0),
    ).generate(_request(), Interpretation)
    assert error_result.status == LLMProviderStatus.ERROR
    assert error_result.output is None
    assert error_result.reason_codes == ("LLM_PROVIDER_TRANSIENT_ERROR",)


async def test_prompt_secret_marker_and_unknown_prompt_are_rejected_pre_call() -> None:
    transport = ScriptedTransport([_valid_response()])
    provider = GeminiStructuredProvider(
        settings=_settings(),
        prompts=_registry(),
        transport=transport,
    )
    sensitive = await provider.generate(
        _request(api_key="must-not-leave-process"),
        Interpretation,
    )
    assert sensitive.reason_codes == ("SENSITIVE_PROMPT_VARIABLE_REJECTED",)
    sensitive_value = await provider.generate(
        _request(evidence_json="GEMINI_API_KEY=test-key-never-sent-in-prompt"),
        Interpretation,
    )
    assert sensitive_value.reason_codes == ("SENSITIVE_PROMPT_VALUE_REJECTED",)
    missing_prompt = await provider.generate(
        _request().model_copy(update={"prompt_version": "missing"}),
        Interpretation,
    )
    assert missing_prompt.reason_codes == ("PROMPT_VERSION_NOT_FOUND",)
    assert transport.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("GEMINI_MAX_RETRIES", -1),
        ("GEMINI_MAX_RETRIES", 6),
        ("GEMINI_REQUEST_TIMEOUT_SECONDS", 0),
        ("GEMINI_REQUEST_TIMEOUT_SECONDS", 301),
    ),
)
def test_existing_chat_gemini_retry_and_timeout_bounds(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        GeminiSettings.model_validate({field: value})
