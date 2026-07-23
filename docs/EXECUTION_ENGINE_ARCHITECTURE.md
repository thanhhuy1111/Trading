# Execution Engine Architecture Specification

## 1. Overview
The Execution Engine processes `ApprovedOrder` contracts emitted by the Deterministic Risk Governor, validates pre-execution safety bounds, plans child orders, and simulates fill execution using `SimulatorExchangeAdapter`.

```
ApprovedOrder -> ExecutionValidationGate -> ExecutionPlanner -> SimulatorExchangeAdapter -> ExchangeOrder & Fills -> ExecutionReport
```

## 2. Invariants & Bounds
- **Simulation Mode ONLY**: Operates strictly in `SIMULATION` mode (`LIVE_TRADING_ENABLED=false`).
- **No Exchange Connection**: Zero private exchange APIs, Binance API keys, or live order placement.
- **Immutable Constraints**: Cannot increase `approved_quantity`, `maximum_notional`, or pay higher than `maximum_entry_price`.
- **Idempotent Submission**: Enforces idempotency via `client_order_id`. Duplicate submissions return existing orders.
