import re
from typing import Any, Dict

REDACTED_TEXT = "[REDACTED]"

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "api_secret",
    "password",
    "pass",
    "auth",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "cookie",
    "jwt",
    "private_key",
    "dsn",
}

DSN_PATTERN = re.compile(r"://([^:]+):([^@]+)@")


class SensitiveDataRedactor:
    """Centralized filter to redact credentials and secrets from logs and telemetry."""

    @staticmethod
    def redact_key_value(key: str, value: Any) -> Any:
        key_lower = key.lower()
        if any(s in key_lower for s in SENSITIVE_KEYS):
            return REDACTED_TEXT
        if isinstance(value, str):
            return SensitiveDataRedactor.redact_string(value)
        if isinstance(value, dict):
            return SensitiveDataRedactor.redact_dict(value)
        if isinstance(value, list):
            return [SensitiveDataRedactor.redact_key_value(key, item) for item in value]
        return value

    @staticmethod
    def redact_string(text: str) -> str:
        if not text:
            return text
        # Redact postgresql://user:pass@host DSN passwords
        redacted = DSN_PATTERN.sub(r"://\1:" + REDACTED_TEXT + r"@", text)
        return redacted

    @staticmethod
    def redact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for k, v in data.items():
            result[k] = SensitiveDataRedactor.redact_key_value(k, v)
        return result


redactor = SensitiveDataRedactor()
