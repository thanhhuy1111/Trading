# Portfolio Ledger Specification

## 1. Entry Types
- `CASH_DEBIT`: Cash spent on BUY fill + fee.
- `CASH_CREDIT`: Net cash proceeds from SELL fill.
- `ASSET_CREDIT`: Base asset received from BUY fill.
- `ASSET_DEBIT`: Base asset released from SELL fill.
- `FEE_DEBIT`: Exchange fee deduction.
- `REALIZED_PNL`: Recorded realized gain/loss upon position reduction or closure.

## 2. Invariants
- Cash balance $\ge 0$.
- Asset balance $\ge 0$.
- Duplicate fill delivery (`(account_id, fill_id)`) returns identical initial entries without altering ledger balances.
