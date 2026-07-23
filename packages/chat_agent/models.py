"""Typed, provider-agnostic contracts for the chat agent layer.

`GeminiProvider` and `FakeLLMProvider` both speak these types -- no `google.genai` type
ever crosses the `LLMProvider` boundary. This is what makes the provider swappable and
the orchestrator's tool-loop logic (round limits, timeouts, audit) testable without a
live Gemini API key.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    role: ChatRole
    content: str
    created_at: datetime


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    # Opaque, provider-specific data a provider may need echoed back on a later turn (e.g.
    # Gemini's thought_signature -- see gemini_provider.py). Never inspected or relied upon
    # by the orchestrator/tool_registry; other providers leave this empty.
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    name: str
    output: Dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    error_message: Optional[str] = None


class TranscriptEntryRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class TranscriptEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: TranscriptEntryRole
    text: Optional[str] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    tool_result: Optional[ToolResult] = None


class AgentToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters_schema: Dict[str, Any]


class AgentRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    system_prompt: str
    transcript: List[TranscriptEntry]
    tools: List[AgentToolDefinition]


class FinishReason(str, Enum):
    STOP = "STOP"
    TOOL_CALLS = "TOOL_CALLS"
    ERROR = "ERROR"


class AgentProviderResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: Optional[str] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason
    model_version: str


class ToolCallAuditEntry(BaseModel):
    call_id: str
    name: str
    arguments_hash: str
    duration_ms: float
    is_error: bool


class ChatTurnResult(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    recommendation_result_id: Optional[str] = None
    proposal_ids: List[str] = Field(default_factory=list)
    tool_call_summary: List[ToolCallAuditEntry] = Field(default_factory=list)
    model: str
    prompt_version: str
    generated_at: datetime
