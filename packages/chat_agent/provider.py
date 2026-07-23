"""LLMProvider abstraction.

    LLMProvider
    └── GeminiProvider   (packages/chat_agent/gemini_provider.py, needs GEMINI_API_KEY)
    └── FakeLLMProvider  (below, deterministic, no network, no API key -- used by tests
                           and safe to use in an offline dev environment)

No API route, RecommendationService, RiskService, or domain model may import
`google.genai` directly -- only gemini_provider.py may.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from packages.chat_agent.models import (
    AgentProviderResult,
    AgentRequest,
    FinishReason,
    ToolCall,
    ToolResult,
    TranscriptEntryRole,
)


class LLMProvider(ABC):
    @abstractmethod
    async def complete_with_tools(self, request: AgentRequest) -> AgentProviderResult: ...


class FakeLLMProvider(LLMProvider):
    """Deterministic scripted provider for tests and offline development.

    Implements exactly the golden-path flow from the implementation plan's system prompt:
    call get_market_overview first; once its result is in the transcript, call
    scan_trade_opportunities; once that result is in the transcript, produce a final
    grounded answer built ONLY from the tool outputs (via response_formatter). It never
    invents a price, probability, or proposal field -- every number in its final text is
    read back out of a ToolResult already present in the transcript.
    """

    model_version = "fake-provider-v1"

    def __init__(self, max_scripted_rounds: int = 5) -> None:
        self._max_scripted_rounds = max_scripted_rounds

    def _tool_names_called(self, request: AgentRequest) -> List[str]:
        return [
            call.name
            for entry in request.transcript
            if entry.role == TranscriptEntryRole.TOOL_CALL
            for call in entry.tool_calls
        ]

    def _last_tool_result(self, request: AgentRequest, name: str) -> Optional[ToolResult]:
        for entry in reversed(request.transcript):
            if entry.role == TranscriptEntryRole.TOOL_RESULT and entry.tool_result and entry.tool_result.name == name:
                return entry.tool_result
        return None

    async def complete_with_tools(self, request: AgentRequest) -> AgentProviderResult:
        available = {t.name for t in request.tools}
        called = self._tool_names_called(request)

        if "get_market_overview" in available and "get_market_overview" not in called:
            return AgentProviderResult(
                tool_calls=[ToolCall(name="get_market_overview", arguments={})],
                finish_reason=FinishReason.TOOL_CALLS,
                model_version=self.model_version,
            )

        market_overview_result = self._last_tool_result(request, "get_market_overview")
        if market_overview_result and market_overview_result.output.get("overall_market_status") == "UNAVAILABLE":
            return AgentProviderResult(
                text="Không thể lấy dữ liệu thị trường vào lúc này. Hệ thống không phát sinh đề xuất giao dịch.",
                finish_reason=FinishReason.STOP,
                model_version=self.model_version,
            )

        if "scan_trade_opportunities" in available and "scan_trade_opportunities" not in called:
            return AgentProviderResult(
                tool_calls=[ToolCall(name="scan_trade_opportunities", arguments={})],
                finish_reason=FinishReason.TOOL_CALLS,
                model_version=self.model_version,
            )

        scan_result = self._last_tool_result(request, "scan_trade_opportunities")
        from packages.chat_agent.response_formatter import format_scan_result_vietnamese

        text = format_scan_result_vietnamese(scan_result.output if scan_result else {})
        return AgentProviderResult(text=text, finish_reason=FinishReason.STOP, model_version=self.model_version)
