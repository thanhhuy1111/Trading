from typing import Any, Dict


class SensitiveDataRedactor:
    """Masks secrets, tokens, API keys, and passwords before audit logging."""

    SENSITIVE_KEYS = {
        "password", "secret", "api_key", "apikey", "binance_secret_key",
        "binance_api_key", "token", "private_key", "authorization", "access_token"
    }

    REDACTED_VALUE = "***REDACTED***"

    @classmethod
    def redact(cls, data: Any) -> Any:
        if isinstance(data, dict):
            redacted_dict: Dict[str, Any] = {}
            for k, v in data.items():
                if k.lower() in cls.SENSITIVE_KEYS:
                    redacted_dict[k] = cls.REDACTED_VALUE
                else:
                    redacted_dict[k] = cls.redact(v)
            return redacted_dict
        elif isinstance(data, list):
            return [cls.redact(item) for item in data]
        elif isinstance(data, str):
            # Mask potential JWT or raw token patterns if present
            if len(data) > 32 and any(term in data.lower() for term in ["bearer", "eyj"]):
                return cls.REDACTED_VALUE
            return data
        else:
            return data
