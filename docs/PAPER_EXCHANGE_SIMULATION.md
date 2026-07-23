# Paper Exchange Simulation Model Specification

## 1. Overview
The `PaperExchangeAdapter` (`packages/paper/adapter.py`) implements `ExchangeExecutionAdapter` with `ExecutionMode.PAPER`. It provides realistic, high-fidelity execution simulation for real-time paper trading.

---

## 2. Fill Pricing Formula
```
Slippage Factor = 1.0005 (BUY) | 0.9995 (SELL)  (5 bps linear impact)
Fill Price = Limit Price * Slippage Factor
Quote Quantity = Fill Quantity * Fill Price
Taker Fee = Quote Quantity * 0.0010 (10 bps fee)
Net Cash Debit (BUY) = Quote Quantity + Fee
Net Cash Credit (SELL) = Quote Quantity - Fee
```

---

## 3. Latency Jitter & Execution Policy
- Latency Jitter Config (`PaperLatencyConfig`):
  - `signal_processing_latency_ms`: 50ms
  - `governance_latency_ms`: 30ms
  - `risk_latency_ms`: 20ms
  - `submission_latency_ms`: 40ms
  - `exchange_ack_latency_ms`: 60ms
  - `latency_jitter_ms`: ±15ms
- `NO_SAME_EVENT_FILL` default policy enforced. Orders submitted on candle close $T$ fill on event $T+1$.

---

## 4. Idempotency Guarantee
Every order submission carries a unique `client_order_id`. Submitting an order with a previously processed `client_order_id` returns the cached `ExchangeOrderResponse` and fills without duplicating portfolio ledger entries or execution events.
