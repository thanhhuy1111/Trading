# Dynamic Configuration Management Specification

## 1. Governance Rules
1. **Pydantic Validation**: All configuration updates must pass strict schema validation.
2. **Financial Precision**: All risk limits (`max_risk_per_trade_pct`, `max_daily_loss_pct`) enforce `Decimal` precision.
3. **Single Active Version**: Only one version can be `ACTIVE` per `(namespace, name)` at any time.
4. **SHA-256 Checksum**: Every configuration set generates a canonical JSON SHA-256 hash.
5. **Mandatory Audit Trail**: Activation and creation of configuration sets write immutable audit log records.

## 2. Default Namespaces
- `system`: System behavior flags.
- `event_bus`: Event bus buffer and retry settings.
- `risk`: Risk Governor limits (`RiskPolicyConfig`).
- `trading`: Trading parameters and symbols.
- `market_data`: Market feed polling and depth settings.
- `observability`: Telemetry, metric export rates.
