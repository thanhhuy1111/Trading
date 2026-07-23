# Event Architecture Specification

## 1. Overview
The platform uses an Event-Driven Architecture (EDA) to decouple services and ensure auditability.

```
+---------------------+     +-----------------------+     +------------------------+
| Domain Event        | --> | Transactional Outbox  | --> | EventBus Adapter       |
| Envelope (CloudEv)  |     | (event_outbox Table)  |     | (Redis / Redpanda)     |
+---------------------+     +-----------------------+     +------------------------+
                                                                       |
                                                                       v
+---------------------+     +-----------------------+     +------------------------+
| Append-Only Audit   | <-- | Consumer Inbox        | <-- | Idempotent Handlers    |
| Log Engine          |     | (event_inbox Table)   |     | (At-Least-Once)        |
+---------------------+     +-----------------------+     +------------------------+
```

## 2. Topic Hierarchy
- `trading.system.events.v1`: System state lifecycle (start, stop, kill switch).
- `trading.config.events.v1`: Configuration changes and activations.
- `trading.market.events.v1`: Market ticks and orderbook updates.
- `trading.intelligence.events.v1`: Agent signals, regime detections, critic votes.
- `trading.risk.events.v1`: Risk evaluations, position checks, drawdown warnings.
- `trading.execution.events.v1`: Order creation, fills, cancellations.
- `trading.audit.events.v1`: Immutable audit log stream.
- `trading.dead-letter.v1`: Dead-letter queue for failed event reprocessing.

## 3. Transactional Outbox & Idempotency
- **Outbox**: Events written atomically within PostgreSQL database transactions before dispatching.
- **Inbox**: Idempotent processing guaranteed by unique DB constraint `(event_id, consumer_name)`.
