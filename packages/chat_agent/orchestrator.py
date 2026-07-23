"""Bounded tool-calling loop: the only place an LLMProvider's tool-call decisions are
turned into actual tool executions.

Enforces: a maximum number of tool-call rounds, a maximum total number of tool calls, a
per-tool timeout, a total request deadline, prompt-injection refusal BEFORE any tool
runs, output-safety filtering on the final answer, and structured audit logging with
secrets redacted. A provider error or timeout never produces a fabricated answer -- it
produces the fixed safe fallback message and no proposal.
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import List, Optional

from packages.chat_agent.config import OrchestratorSettings, orchestrator_settings
from packages.chat_agent.conversation_service import ConversationRepository, conversation_repository
from packages.chat_agent.exceptions import ToolValidationError, UnsupportedToolError
from packages.chat_agent.guardrails import (
    SAFE_FALLBACK_ANSWER_VI,
    detect_prompt_injection,
    enforce_output_safety,
    redact_secrets,
)
from packages.chat_agent.models import (
    AgentRequest,
    ChatMessage,
    ChatRole,
    ChatTurnResult,
    FinishReason,
    ToolCallAuditEntry,
    ToolResult,
    TranscriptEntry,
    TranscriptEntryRole,
)
from packages.chat_agent.prompts import SYSTEM_PROMPT_VERSION, SYSTEM_PROMPT_VI
from packages.chat_agent.provider import LLMProvider
from packages.chat_agent.tool_registry import ToolRegistry, tool_registry
from packages.common.logger import logger
from packages.telemetry.metrics import metrics_registry


def _hash_arguments(arguments: dict) -> str:
    payload = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class TradingAdvisorOrchestrator:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry = tool_registry,
        conversations: ConversationRepository = conversation_repository,
        settings: OrchestratorSettings = orchestrator_settings,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._conversations = conversations
        self._settings = settings

    def _history_to_transcript(self, messages: List[ChatMessage]) -> List[TranscriptEntry]:
        entries = []
        for m in messages:
            role = TranscriptEntryRole.USER if m.role == ChatRole.USER else TranscriptEntryRole.ASSISTANT
            entries.append(TranscriptEntry(role=role, text=m.content))
        return entries

    async def handle_message(self, conversation_id: Optional[str], user_message: str) -> ChatTurnResult:
        metrics_registry.increment_counter("chat_requests_total", {})
        now = datetime.now(timezone.utc)

        if len(user_message) > self._settings.CHAT_MAX_PROMPT_CHARS:
            user_message = user_message[: self._settings.CHAT_MAX_PROMPT_CHARS]

        if conversation_id:
            conversation = await self._conversations.get(conversation_id)
            if conversation is None:
                conversation = await self._conversations.create()
        else:
            conversation = await self._conversations.create()

        user_chat_message = ChatMessage(role=ChatRole.USER, content=user_message, created_at=now)
        conversation = await self._conversations.append_message(conversation.conversation_id, user_chat_message)

        injection_matches = detect_prompt_injection(user_message)
        audit: List[ToolCallAuditEntry] = []
        proposal_ids: List[str] = []
        recommendation_result_id: Optional[str] = None

        if injection_matches:
            logger.warning(
                "chat_prompt_injection_blocked",
                extra={"conversation_id": conversation.conversation_id, "matched_patterns": injection_matches},
            )
            metrics_registry.increment_counter("chat_guardrail_blocks_total", {"reason_code": "prompt_injection"})
            final_text = (
                "Yêu cầu này nằm ngoài phạm vi hỗ trợ (ví dụ: bỏ qua kiểm soát rủi ro, tiết lộ thông tin "
                "bảo mật, hoặc thực thi lệnh hệ thống/giao dịch trực tiếp). Tôi không thể thực hiện yêu cầu này."
            )
        else:
            final_text, transcript = await self._run_tool_loop(
                conversation.conversation_id, conversation.messages, audit
            )
            recommendation_result_id, proposal_ids = self._extract_recommendation_facts(transcript)
            for entry in audit:
                if entry.name == "scan_trade_opportunities":
                    metrics_registry.increment_counter("recommendation_scans_total", {})

        final_text = enforce_output_safety(final_text)

        assistant_message = ChatMessage(
            role=ChatRole.ASSISTANT, content=final_text, created_at=datetime.now(timezone.utc)
        )
        await self._conversations.append_message(conversation.conversation_id, assistant_message)

        model_version = getattr(self._provider, "model_version", "unknown")

        return ChatTurnResult(
            conversation_id=conversation.conversation_id,
            message_id=assistant_message.message_id,
            answer=final_text,
            recommendation_result_id=recommendation_result_id,
            proposal_ids=proposal_ids,
            tool_call_summary=audit,
            model=model_version,
            prompt_version=SYSTEM_PROMPT_VERSION,
            generated_at=datetime.now(timezone.utc),
        )

    async def _run_tool_loop(
        self, conversation_id: str, history: List[ChatMessage], audit: List[ToolCallAuditEntry]
    ) -> tuple[str, List[TranscriptEntry]]:
        transcript = self._history_to_transcript(history)
        tool_defs = self._tools.definitions()
        deadline = time.monotonic() + self._settings.CHAT_TOTAL_REQUEST_DEADLINE_SECONDS
        total_tool_calls = 0

        for _round_index in range(self._settings.CHAT_MAX_TOOL_ROUNDS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                metrics_registry.increment_counter("chat_failures_total", {"reason_code": "deadline_exceeded"})
                return SAFE_FALLBACK_ANSWER_VI, transcript

            request = AgentRequest(system_prompt=SYSTEM_PROMPT_VI, transcript=transcript, tools=tool_defs)
            try:
                result = await asyncio.wait_for(self._provider.complete_with_tools(request), timeout=remaining)
            except asyncio.TimeoutError:
                metrics_registry.increment_counter("gemini_errors_total", {"reason_code": "timeout"})
                return SAFE_FALLBACK_ANSWER_VI, transcript
            except Exception as exc:  # noqa: BLE001 - provider failures must never crash the chat turn
                logger.error(
                    "chat_provider_error", extra={"conversation_id": conversation_id, "error": redact_secrets(str(exc))}
                )
                metrics_registry.increment_counter("gemini_errors_total", {"reason_code": "exception"})
                return SAFE_FALLBACK_ANSWER_VI, transcript

            if result.finish_reason != FinishReason.TOOL_CALLS or not result.tool_calls:
                return result.text or SAFE_FALLBACK_ANSWER_VI, transcript

            transcript.append(TranscriptEntry(role=TranscriptEntryRole.TOOL_CALL, tool_calls=result.tool_calls))

            for call in result.tool_calls:
                if total_tool_calls >= self._settings.CHAT_MAX_TOTAL_TOOL_CALLS:
                    tool_result = ToolResult(
                        call_id=call.call_id, name=call.name, output={}, is_error=True,
                        error_message="TOOL_CALL_BUDGET_EXCEEDED",
                    )
                else:
                    total_tool_calls += 1
                    tool_result = await self._execute_tool_call(conversation_id, call, audit)
                transcript.append(TranscriptEntry(role=TranscriptEntryRole.TOOL_RESULT, tool_result=tool_result))

        metrics_registry.increment_counter("chat_failures_total", {"reason_code": "max_rounds_exceeded"})
        return SAFE_FALLBACK_ANSWER_VI, transcript

    def _extract_recommendation_facts(self, transcript: List[TranscriptEntry]) -> tuple[Optional[str], List[str]]:
        recommendation_result_id: Optional[str] = None
        proposal_ids: List[str] = []
        for entry in transcript:
            if entry.role != TranscriptEntryRole.TOOL_RESULT or entry.tool_result is None:
                continue
            result = entry.tool_result
            if result.is_error:
                continue
            if result.name == "scan_trade_opportunities":
                recommendation_result_id = result.output.get("request_id") or recommendation_result_id
                proposal_ids.extend(
                    p.get("proposal_id") for p in result.output.get("proposals", []) if p.get("proposal_id")
                )
            elif result.name == "analyze_trade_proposal" and result.output.get("found"):
                pid = result.output.get("proposal_id")
                if pid and pid not in proposal_ids:
                    proposal_ids.append(pid)
        return recommendation_result_id, proposal_ids

    async def _execute_tool_call(self, conversation_id: str, call, audit: List[ToolCallAuditEntry]) -> ToolResult:
        started = time.monotonic()
        metrics_registry.increment_counter("chat_tool_calls_total", {"component": call.name})
        try:
            output = await asyncio.wait_for(
                self._tools.execute(call.name, call.arguments), timeout=orchestrator_settings.CHAT_TOOL_TIMEOUT_SECONDS
            )
            tool_result = ToolResult(call_id=call.call_id, name=call.name, output=output)
        except UnsupportedToolError as exc:
            tool_result = ToolResult(
                call_id=call.call_id, name=call.name, output={}, is_error=True, error_message=redact_secrets(str(exc))
            )
        except (ToolValidationError, ValueError) as exc:
            tool_result = ToolResult(
                call_id=call.call_id, name=call.name, output={}, is_error=True, error_message=redact_secrets(str(exc))
            )
        except asyncio.TimeoutError:
            tool_result = ToolResult(
                call_id=call.call_id, name=call.name, output={}, is_error=True, error_message="TOOL_TIMEOUT"
            )
        except Exception as exc:  # noqa: BLE001 - a single tool bug must never crash the chat turn
            logger.error(
                "chat_tool_execution_failed",
                extra={"conversation_id": conversation_id, "tool": call.name, "error": redact_secrets(str(exc))},
            )
            tool_result = ToolResult(
                call_id=call.call_id, name=call.name, output={}, is_error=True, error_message="TOOL_EXECUTION_FAILED"
            )

        duration_ms = (time.monotonic() - started) * 1000
        entry = ToolCallAuditEntry(
            call_id=call.call_id,
            name=call.name,
            arguments_hash=_hash_arguments(call.arguments),
            duration_ms=duration_ms,
            is_error=tool_result.is_error,
        )
        audit.append(entry)
        logger.info(
            "chat_tool_call",
            extra={
                "conversation_id": conversation_id,
                "tool": call.name,
                "arguments_hash": entry.arguments_hash,
                "duration_ms": duration_ms,
                "is_error": tool_result.is_error,
            },
        )
        if tool_result.is_error:
            metrics_registry.increment_counter("proposal_validation_failures_total", {"component": call.name})
        return tool_result


def build_default_orchestrator(provider: LLMProvider) -> TradingAdvisorOrchestrator:
    return TradingAdvisorOrchestrator(provider=provider)
