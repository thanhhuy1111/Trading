# Distributed Tracing Policy

## Standard Protocol
Distributed tracing follows OpenTelemetry standards, wrapping execution blocks in spans and context handlers:
```python
with tracer.start_span("process_candle_close", telemetry_ctx) as span:
    span.set_attribute("symbol", candle.symbol)
    ...
```

## Context Propagation
`TelemetryContext` is passed across service boundaries (HTTP API, event bus, outbox queue, worker tasks) to maintain trace continuity.
