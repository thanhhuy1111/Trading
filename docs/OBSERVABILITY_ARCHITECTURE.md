# Observability Architecture

## System Overview
The Observability Architecture provides unified, end-to-end operational visibility across all components of the crypto multi-agent trading platform while strictly enforcing execution boundaries (`LIVE_TRADING_ENABLED=false`).

```
+-------------------------------------------------------------------------+
|                      React Operational Dashboard                        |
|   - System Status  - Pipeline Lineage  - Incidents  - Metrics / SLO     |
+-------------------------------------------------------------------------+
                                    ^
                                    | REST API (/operations/*, /metrics)
+-------------------------------------------------------------------------+
|                       FastAPI Backend Service                           |
|   - Health API    - Metrics Registry   - Lineage API  - Incidents API   |
+-------------------------------------------------------------------------+
            ^                       ^                       ^
            |                       |                       |
+----------------------+  +--------------------+  +--------------------+
|  Metrics Engine      |  | Tracing Protocol   |  | Redaction Filter   |
| (trading_system_*)   |  | (TelemetryContext) |  | (Mask Credentials) |
+----------------------+  +--------------------+  +--------------------+
            ^                       ^                       ^
            +-----------------------+-----------------------+
                                    |
+-------------------------------------------------------------------------+
|                      PostgreSQL Storage Tables                          |
|   operational_incidents       slo_definitions        alert_rules        |
|   pipeline_lineage_records    component_health       retention_policy   |
+-------------------------------------------------------------------------+
```

## Core Guarantees
1. **Zero State Mutation**: Telemetry and observability operations MUST NOT mutate trading states, bypass Risk Governor, or enable live trading.
2. **Fail-Open Telemetry**: Failure of observability backends (Loki, Tempo, Prometheus) MUST NOT halt trading pipeline execution.
3. **Strict Credential Redaction**: All API keys, secrets, DSNs, and authorization tokens are automatically sanitized before storage or display.
