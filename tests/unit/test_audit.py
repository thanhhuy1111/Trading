from packages.audit.redactor import SensitiveDataRedactor


def test_sensitive_data_redactor_masks_secrets():
    payload = {
        "user_id": "user_123",
        "binance_api_key": "secret_key_12345",
        "binance_secret_key": "super_secret_67890",
        "nested": {
            "password": "my_password_123",
            "safe_field": "visible_data"
        }
    }
    redacted = SensitiveDataRedactor.redact(payload)
    assert redacted["user_id"] == "user_123"
    assert redacted["binance_api_key"] == "***REDACTED***"
    assert redacted["binance_secret_key"] == "***REDACTED***"
    assert redacted["nested"]["password"] == "***REDACTED***"
    assert redacted["nested"]["safe_field"] == "visible_data"
