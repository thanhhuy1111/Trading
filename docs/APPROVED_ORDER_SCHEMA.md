# ApprovedOrder Schema Specification

```json
{
  "approved_order_id": "uuid",
  "client_order_id": "uuid",
  "risk_decision_id": "uuid",
  "intent_id": "uuid",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "side": "BUY",
  "approved_quantity": "0.19200000",
  "maximum_notional": "12492.48000000",
  "approved_stop_price": "63700.00000000",
  "maximum_entry_price": "65065.00000000",
  "maximum_entry_slippage_bps": "10.0000",
  "expires_at": "2026-07-22T13:15:00Z",
  "risk_policy_version": "1.0.0",
  "governor_version": "1.0.0",
  "status": "PENDING_EXECUTION",
  "schema_version": 1
}
```

> [!IMPORTANT]
> The schema strictly excludes `exchange_order_id`, `fill_quantity`, `fill_price`, `execution_status`, and `api_key`.
> Orders are passed to Milestone 7 Execution Engine for simulated/live execution.
