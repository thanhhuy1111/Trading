# Execution Reconciliation Specification

## 1. Reconciliation Strategy
- Ambiguous submissions (`UNKNOWN` status) trigger query by `client_order_id`.
- Reconciles existing simulator state without generating new order IDs or altering price/quantity limits.
- Restart recovery rebuilds order state projections directly from database records.
