"""GeminiProvider: the ONLY module in this repository allowed to import `google.genai`.

Converts the provider-agnostic AgentRequest/AgentProviderResult contract (models.py) to
and from the google-genai SDK's types. Uses `client.aio.models.generate_content` (async,
matches this project's async-first stack) with `automatic_function_calling` disabled --
tool execution is entirely owned by packages/chat_agent/orchestrator.py so every call
goes through the allowlist, timeouts, and audit logging there, never inside the SDK.

Verified live 2026-07-24: models with thinking enabled (this project's default
GEMINI_THINKING_LEVEL) return a `thought_signature` on each function-call `Part`, and
reject a follow-up request that replays that function call without echoing the same
signature back (400 INVALID_ARGUMENT: "Function call is missing a thought_signature").
`_parse_response` captures it into `ToolCall.provider_metadata` and `_to_contents` replays
it -- see https://ai.google.dev/gemini-api/docs/thought-signatures.
"""

import asyncio
import base64
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from packages.chat_agent.config import GeminiSettings, gemini_settings
from packages.chat_agent.exceptions import ProviderError, ProviderTimeoutError
from packages.chat_agent.models import (
    AgentProviderResult,
    AgentRequest,
    AgentToolDefinition,
    FinishReason,
    ToolCall,
    TranscriptEntryRole,
)
from packages.chat_agent.provider import LLMProvider

_THINKING_LEVELS = {"MINIMAL", "LOW", "MEDIUM", "HIGH"}


class GeminiProvider(LLMProvider):
    def __init__(self, settings: GeminiSettings = gemini_settings) -> None:
        if not settings.GEMINI_API_KEY:
            raise ProviderError("GEMINI_API_KEY is not configured")
        self._settings = settings
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    @property
    def model_version(self) -> str:
        return self._settings.GEMINI_MODEL

    def _build_tools(self, tools: List[AgentToolDefinition]) -> List[types.Tool]:
        declarations = [
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters_json_schema=t.parameters_schema
            )
            for t in tools
        ]
        gemini_tools = [types.Tool(function_declarations=declarations)] if declarations else []
        if self._settings.GEMINI_ENABLE_GOOGLE_SEARCH:
            # Never used on the trade-recommendation path: the orchestrator only ever
            # passes the fixed 5-tool allowlist here, and search is not one of them. This
            # flag only matters for a separate, disabled-by-default News Research feature
            # that is NOT implemented in this repository (see architecture doc).
            gemini_tools.append(types.Tool(google_search=types.GoogleSearch()))
        return gemini_tools

    def _to_contents(self, request: AgentRequest) -> List[types.Content]:
        contents: List[types.Content] = []
        for entry in request.transcript:
            if entry.role == TranscriptEntryRole.USER and entry.text:
                contents.append(types.Content(role="user", parts=[types.Part(text=entry.text)]))
            elif entry.role == TranscriptEntryRole.ASSISTANT and entry.text:
                contents.append(types.Content(role="model", parts=[types.Part(text=entry.text)]))
            elif entry.role == TranscriptEntryRole.TOOL_CALL:
                parts = []
                for c in entry.tool_calls:
                    thought_signature: Optional[bytes] = None
                    raw_signature = c.provider_metadata.get("thought_signature_b64")
                    if raw_signature:
                        thought_signature = base64.b64decode(raw_signature)
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(id=c.call_id, name=c.name, args=c.arguments),
                            thought_signature=thought_signature,
                        )
                    )
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif entry.role == TranscriptEntryRole.TOOL_RESULT and entry.tool_result:
                tr = entry.tool_result
                response: Dict[str, Any] = {"error": tr.error_message} if tr.is_error else tr.output
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=tr.call_id, name=tr.name, response=response
                                )
                            )
                        ],
                    )
                )
        return contents

    def _thinking_config(self) -> Optional[types.ThinkingConfig]:
        level = self._settings.GEMINI_THINKING_LEVEL.upper()
        if level not in _THINKING_LEVELS:
            level = "MINIMAL"
        return types.ThinkingConfig(thinking_level=getattr(types.ThinkingLevel, level))

    def _parse_response(self, response: "types.GenerateContentResponse") -> AgentProviderResult:
        if not response.candidates:
            return AgentProviderResult(finish_reason=FinishReason.ERROR, model_version=self.model_version)

        candidate = response.candidates[0]
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text_parts.append(part.text)
                if part.function_call and part.function_call.name:
                    fc = part.function_call
                    assert fc.name is not None
                    call_id = fc.id or fc.name
                    provider_metadata: Dict[str, Any] = {}
                    if part.thought_signature:
                        provider_metadata["thought_signature_b64"] = base64.b64encode(
                            part.thought_signature
                        ).decode("ascii")
                    tool_calls.append(
                        ToolCall(
                            call_id=call_id, name=fc.name, arguments=dict(fc.args or {}),
                            provider_metadata=provider_metadata,
                        )
                    )

        if tool_calls:
            return AgentProviderResult(
                tool_calls=tool_calls, finish_reason=FinishReason.TOOL_CALLS, model_version=self.model_version
            )
        return AgentProviderResult(
            text="\n".join(text_parts) or None, finish_reason=FinishReason.STOP, model_version=self.model_version
        )

    async def complete_with_tools(self, request: AgentRequest) -> AgentProviderResult:
        config = types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            tools=self._build_tools(request.tools),
            thinking_config=self._thinking_config(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = self._to_contents(request)

        last_error: Optional[Exception] = None
        for attempt in range(self._settings.GEMINI_MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=self._settings.GEMINI_MODEL, contents=contents, config=config
                    ),
                    timeout=self._settings.GEMINI_REQUEST_TIMEOUT_SECONDS,
                )
                return self._parse_response(response)
            except asyncio.TimeoutError as exc:
                last_error = exc
                timeout_s = self._settings.GEMINI_REQUEST_TIMEOUT_SECONDS
                raise ProviderTimeoutError(f"Gemini request timed out after {timeout_s}s") from exc
            except Exception as exc:  # noqa: BLE001 - translate every SDK error uniformly
                last_error = exc
                if attempt < self._settings.GEMINI_MAX_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise ProviderError(f"Gemini request failed: {exc}") from exc

        raise ProviderError(f"Gemini request failed: {last_error}")
