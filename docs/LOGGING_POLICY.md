# Logging Policy & Redaction Strategy

## JSON Formatter
All application logs are formatted in JSON with consistent keys: `timestamp`, `level`, `message`, `logger_name`, `correlation_id`, `service`.

## Sensitive Data Masking
`SensitiveDataRedactor` automatically intercepts and replaces sensitive key-value pairs:
- `api_key`, `secret`, `password`, `authorization`, `token`, `cookie` → `[REDACTED]`
- Database DSN connection strings (`postgresql://user:pass@host`) → `postgresql://user:[REDACTED]@host`
