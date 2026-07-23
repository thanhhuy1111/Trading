from pydantic_settings import BaseSettings, SettingsConfigDict


class GeminiSettings(BaseSettings):
    """Gemini provider configuration. GEMINI_API_KEY is never logged, printed, returned
    to a client, or included in any serialized model -- it is read once here and passed
    directly to the google-genai client.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_THINKING_LEVEL: str = "MINIMAL"  # MINIMAL | LOW | MEDIUM | HIGH
    GEMINI_ENABLE_GOOGLE_SEARCH: bool = False
    GEMINI_REQUEST_TIMEOUT_SECONDS: float = 30.0
    GEMINI_MAX_RETRIES: int = 2

    @property
    def is_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY)


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    CHAT_MAX_TOOL_ROUNDS: int = 6
    CHAT_MAX_TOTAL_TOOL_CALLS: int = 10
    CHAT_TOOL_TIMEOUT_SECONDS: float = 20.0
    CHAT_TOTAL_REQUEST_DEADLINE_SECONDS: float = 60.0
    CHAT_MAX_PROMPT_CHARS: int = 4000
    ENABLE_NEWS_RESEARCH: bool = False


gemini_settings = GeminiSettings()
orchestrator_settings = OrchestratorSettings()
