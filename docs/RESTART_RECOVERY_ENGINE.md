# Restart Recovery Engine Specification

## 1. Overview
The Restart Recovery Engine (`packages/paper/recovery.py`) restores Paper Trading session state following application restart, process crash, or network disconnect without creating duplicate orders or fills.

---

## 2. Recovery Workflow

```mermaid
sequenceDiagram
    participant S as Service Startup
    participant M as Session Manager
    participant J as Event Journal
    participant R as Recovery Engine
    participant A as Paper Adapter

    S->>M: Query Halted/Paused Sessions
    M-->>R: Active Session #S1 (HALTED)
    R->>M: Transition status to RECOVERY_REQUIRED
    R->>J: Fetch Journal Entries for #S1
    J-->>R: Unprocessed Events & Fills
    R->>A: Verify Order Idempotency Map
    R->>M: Restore Positions & Portfolio Ledger State
    R->>M: Transition status to READY / RUNNING
```

---

## 3. Idempotency & Zero Duplicate Guarantee
- `PaperExchangeAdapter` maintains an in-memory & journal-backed index of `client_order_id`.
- Replayed order submission events return existing fills without generating new execution transactions.
- Portfolio ledger ignores duplicate fill IDs via `processed_fill_ids`.
