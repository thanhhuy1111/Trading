# Attack Surface Inventory

## Entry Points
1. **REST API Endpoints**: `/api/v1/*`, `/operations/*`, `/security/*`
2. **WebSocket Ingress**: Public Binance Market Data Stream
3. **Configuration Interface**: Environment variable configuration schema
4. **Interactive Dashboard**: Single Page React Dashboard (`apps/dashboard`)

## Hardening Controls
- Input Validation (`input_validator.validate_decimal_amount`, payload size caps).
- Output DTO Sanitization (`output_sanitizer.sanitize_response_dto`).
- Internal network isolation for PostgreSQL and Redis.
