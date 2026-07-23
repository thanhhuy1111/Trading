# Telemetry Contract

## Overview
The Telemetry Contract defines the standardized metadata structure required across all events, spans, and log records within the system.

## TelemetryContext Model
```python
class TelemetryContext(BaseModel):
    trace_id: str          # Hex trace identifier
    span_id: str           # 16-character span identifier
    correlation_id: UUID   # Pipeline correlation identifier
    causation_id: Optional[UUID]
    event_id: Optional[UUID]
    session_id: Optional[UUID]
    symbol: Optional[str]
    timeframe: Optional[str]
    schema_version: int = 1
```

## Guarantees
- `correlation_id` is generated at market event ingress and propagated through features, signals, critic, allocator, risk governor, order, fill, and ledger events.
- `schema_version` is tracked across all telemetry envelopes.
