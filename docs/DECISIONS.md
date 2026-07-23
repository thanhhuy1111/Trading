# Architecture Decision Records (ADR)

This document logs key architectural decisions, rationale, and tradeoffs made for the Multi-Agent Cryptocurrency Trading System.

---

## ADR-001: 3-Tier Separation of Power Architecture

* **Status**: APPROVED & ENFORCED
* **Context**: LLMs and autonomous AI agents are non-deterministic and can produce uncalibrated outputs or hallucinations. Giving an AI agent direct access to exchange order placement APIs or position sizing calculations poses severe capital ruin risk.
* **Decision**: Enforce a strict 3-tier boundary:
  1. **Intelligence Tier**: Analyzes market data and outputs `AgentSignal` & `TradeIntent`. Has ZERO order execution API access and CANNOT specify trade quantity.
  2. **Risk Governor Tier**: Independent, deterministic Python engine. Evaluates `TradeIntent` against hard NAV risk limits (0.25% risk/trade, 1.5% daily loss limit, 8% hard drawdown kill-switch). Calculates final `approved_quantity`. Has veto power over all orders. NO LLMs allowed for official financial calculations.
  3. **Execution Engine Tier**: Receives ONLY approved `ApprovedOrder` payloads. Manages order lifecycle via idempotent state machine. Cannot modify sizing or strategy logic.
* **Consequences**: Ensures 100% mathematical risk enforcement while leveraging multi-agent market analysis.

---

## ADR-002: Financial Precision via `decimal.Decimal`

* **Status**: APPROVED & ENFORCED
* **Context**: Binary floating-point representation (`float`) introduces precision errors (e.g. `0.1 + 0.2 != 0.3`) which can lead to invalid order sizes, rounding slippage, and balance discrepancies on cryptocurrency exchanges.
* **Decision**: All prices, quantities, notionals, PnL, fees, and stop prices across domain models (`packages/schemas/`) MUST use Python's `decimal.Decimal`. Float is strictly prohibited for money and volume fields.
* **Consequences**: Eliminates floating-point rounding bugs across orders, fills, and portfolio accounting.

---

## ADR-003: Idempotent Execution & Client Order ID Generation

* **Status**: APPROVED & ENFORCED
* **Context**: Network timeouts or WebSocket disconnects during order submission can lead to duplicate order placement if retried blindly.
* **Decision**: Every `ApprovedOrder` and `ExchangeOrder` generated MUST carry a unique string UUID `client_order_id`. Exchange adapters MUST pass this ID to the exchange and check for duplicate submissions before re-transmitting orders.
* **Consequences**: Guarantees safe retries without duplicate execution risk.

---

## ADR-004: Docker Compose Minimal vs Full Profiles

* **Status**: APPROVED & ENFORCED
* **Context**: Running the complete infrastructure stack (PostgreSQL, Redis, ClickHouse, Redpanda, MinIO, MLflow) for local development or lightweight testing can overburden local system resources.
* **Decision**: Configure `docker-compose.yml` with two operational profiles:
  - `minimal` profile: PostgreSQL, Redis, Backend API, Frontend Dashboard (enables fast local MVP development).
  - `full` profile: PostgreSQL, Redis, ClickHouse, Redpanda, Backend API, Frontend Dashboard (for full-scale event-driven analytics and backtesting).
* **Consequences**: Allows developers to launch the core platform instantly without unnecessary resource overhead.

---

## ADR-005: Transactional Outbox Pattern for Durable At-Least-Once Publishing

* **Status**: APPROVED & ENFORCED
* **Context**: Direct async message publishing to a message broker during database state updates can result in lost events if the broker call fails or the process crashes mid-operation.
* **Decision**: All domain events must be saved into the `event_outbox` table within the active database transaction. An asynchronous background `OutboxPublisherWorker` polls pending outbox records using `FOR UPDATE SKIP LOCKED` batching and dispatches them to the `EventPublisher`. The Transactional Outbox provides durable at-least-once publishing after database commit. Consumers must remain idempotent because duplicate delivery can occur.
* **Consequences**: Prevents lost events before database commit while acknowledging potential duplicate publishing.

---

## ADR-006: Consumer Inbox Idempotent Processing Management

* **Status**: APPROVED & ENFORCED
* **Context**: At-least-once message delivery from message brokers (Redis Streams or Redpanda/Kafka) can deliver duplicate event messages to downstream consumers.
* **Decision**: Wrap consumer event handlers with `IdempotentConsumerPipeline` using an `event_inbox` table with a unique constraint on `(event_id, consumer_name)`. The inbox record and business effect must be executed within the same database transaction to achieve idempotent processing and guarantee an effectively-once business effect.
* **Consequences**: Guarantees idempotent business processing across repeated event deliveries.

---

## ADR-007: Append-Only Audit Logging with Secret Masking

* **Status**: APPROVED & ENFORCED
* **Context**: Audit logs must be tamper-proof and sensitive user data (API keys, secrets, passwords, JWT tokens) must never be persisted in plain text.
* **Decision**: `AuditRepository` strictly implements `create` and `query` operations with **NO** `update` or `delete` methods. All log entries are pre-processed through `SensitiveDataRedactor` to mask sensitive fields across nested dictionaries and arrays.
* **Consequences**: Ensures regulatory audit compliance and prevents credentials from leaking into log storage.

---

## Known Technical Debt & Ongoing Verification Log

1. **Redpanda Integration**: Live Redpanda cluster integration pending verification in full profile environment.
2. **Redis Recovery**: Redis pending entries recovery and dead-letter queue require ongoing live stress testing.
3. **Audit Database Immutability**: Application-layer append-only is guaranteed; database role-level append-only requires explicit `REVOKE UPDATE, DELETE ON audit_events` on production PostgreSQL roles.
