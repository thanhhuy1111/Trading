from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GeminiSettings(BaseSettings):
    """Gemini provider configuration. GEMINI_API_KEY is never logged, printed, returned
    to a client, or included in any serialized model -- it is read once here and passed
    directly to the google-genai client.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    GEMINI_API_KEY: str = Field(default="", exclude=True, repr=False)
    GEMINI_MODEL: str = ""
    GEMINI_THINKING_LEVEL: str = "MINIMAL"  # MINIMAL | LOW | MEDIUM | HIGH
    GEMINI_ENABLE_GOOGLE_SEARCH: bool = False
    GEMINI_REQUEST_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=300)
    GEMINI_MAX_RETRIES: int = Field(default=2, ge=0, le=5)

    @property
    def is_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY and self.GEMINI_MODEL)


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    CHAT_MAX_TOOL_ROUNDS: int = 6
    CHAT_MAX_TOTAL_TOOL_CALLS: int = 10
    CHAT_TOOL_TIMEOUT_SECONDS: float = 20.0
    CHAT_TOTAL_REQUEST_DEADLINE_SECONDS: float = 60.0
    CHAT_MAX_PROMPT_CHARS: int = 4000
    ENABLE_NEWS_RESEARCH: bool = False
    # Minimal API-key control for the advisor's own routes -- see apps/api/dependencies.py.
    ADVISOR_API_KEY: str = ""
    # Coarse, process-global rate limits (no per-user identity exists in this system yet).
    CHAT_RATE_LIMIT_PER_MINUTE: int = 30
    RECOMMENDATION_SCAN_RATE_LIMIT_PER_MINUTE: int = 60


gemini_settings = GeminiSettings()
orchestrator_settings = OrchestratorSettings()
