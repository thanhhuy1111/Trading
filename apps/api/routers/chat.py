"""POST /api/v1/chat -- the AI Trading Advisor conversational endpoint.

Routes to a GeminiProvider-backed TradingAdvisorOrchestrator. If GEMINI_API_KEY is not
configured, returns 503 rather than silently falling back to fabricated or fixture data.
Never returns internal exceptions, chain-of-thought, or the API key to the client.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.api.dependencies import enforce_chat_rate_limit, require_advisor_api_key
from packages.chat_agent.config import gemini_settings
from packages.chat_agent.exceptions import ChatAgentError
from packages.chat_agent.gemini_provider import GeminiProvider
from packages.chat_agent.models import ToolCallAuditEntry
from packages.chat_agent.orchestrator import TradingAdvisorOrchestrator
from packages.common.logger import logger

router = APIRouter(prefix="/api/v1", tags=["AI Trading Advisor"])

_orchestrator: Optional[TradingAdvisorOrchestrator] = None


def get_orchestrator() -> TradingAdvisorOrchestrator:
    """Default orchestrator factory (GeminiProvider). Overridden in tests via
    `app.dependency_overrides[get_orchestrator]` to inject a FakeLLMProvider-backed one.
    """
    global _orchestrator
    if not gemini_settings.is_configured:
        raise HTTPException(status_code=503, detail="AI Trading Advisor is not configured (GEMINI_API_KEY missing)")
    if _orchestrator is None:
        _orchestrator = TradingAdvisorOrchestrator(provider=GeminiProvider(gemini_settings))
    return _orchestrator


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    recommendation_result_id: Optional[str] = None
    proposal_ids: List[str] = Field(default_factory=list)
    tool_call_summary: List[ToolCallAuditEntry] = Field(default_factory=list)
    model: str
    prompt_version: str
    generated_at: datetime


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(require_advisor_api_key), Depends(enforce_chat_rate_limit)],
)
async def chat(
    request: ChatRequest, orchestrator: TradingAdvisorOrchestrator = Depends(get_orchestrator)  # noqa: B008
) -> ChatResponse:
    try:
        result = await orchestrator.handle_message(request.conversation_id, request.message)
    except ChatAgentError as exc:
        logger.error("chat_request_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="AI Trading Advisor could not process this request") from exc

    return ChatResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        answer=result.answer,
        recommendation_result_id=result.recommendation_result_id,
        proposal_ids=result.proposal_ids,
        tool_call_summary=result.tool_call_summary,
        model=result.model,
        prompt_version=result.prompt_version,
        generated_at=result.generated_at,
    )
