# Risk Governor Architecture Specification

## 1. Overview
The Deterministic Risk Governor is an independent safety component holding absolute veto power over incoming trade intents (`TradeIntent`).

```
TradeIntent -> Intent Validation -> Portfolio Risk Snapshot -> Hard Risk Checks -> Risk Budget -> Sizing -> RiskDecision & ApprovedOrder
```

## 2. Invariants & Rules
- **Absolute Determinism**: Zero LLM involvement in risk calculations or decision making.
- **No Order Execution**: Issues `ApprovedOrder` (`status="PENDING_EXECUTION"`) ONLY. It does NOT call exchange APIs or place orders.
- **Decimal Precision & Round Down**: Quantities are calculated in `Decimal`, rounded DOWN to step size, and verified to ensure actual risk does not exceed budget.
- **Fail-Closed Design**: Live trading, leverage, shorting, and margin trading are strictly prohibited.
