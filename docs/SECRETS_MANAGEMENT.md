# Secrets Management Policy

## Rules
- Zero hardcoded secrets, passwords, or API keys in source code.
- Environment variables backed by `.env` with strict typed schema validation in `Settings`.
- Startup assertions verify `LIVE_TRADING_ENABLED=false` and `PRIVATE_EXCHANGE_API_ENABLED=false`.
- All telemetry logs pass through `SensitiveDataRedactor` masking sensitive key-value pairs.
