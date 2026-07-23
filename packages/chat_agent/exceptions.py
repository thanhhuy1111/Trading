class ChatAgentError(Exception):
    """Base exception for the chat agent layer."""


class UnsupportedToolError(ChatAgentError):
    """Raised when the model requests a tool name outside the allowlisted registry."""


class ToolValidationError(ChatAgentError):
    """Raised when tool call arguments or a tool's output fail schema validation."""


class PromptInjectionDetected(ChatAgentError):
    """Raised (and caught by the orchestrator) when a user message matches a known
    prompt-injection pattern targeting safety-critical behaviour."""


class ProviderTimeoutError(ChatAgentError):
    """Raised when the LLM provider does not respond within the configured deadline."""


class ProviderError(ChatAgentError):
    """Raised when the LLM provider call fails for any other reason."""


class ConversationNotFoundError(ChatAgentError):
    """Raised when a conversation_id does not exist in the ConversationRepository."""
