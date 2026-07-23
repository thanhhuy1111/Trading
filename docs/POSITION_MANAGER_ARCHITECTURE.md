# Position Manager Architecture Specification

## 1. Overview
The Position Manager consumes executed fills, updates the append-only `PortfolioLedger`, maintains position projections, tracks weighted average cost basis, calculates realized & unrealized PnL, monitors exit triggers, and provides `PortfolioRiskSnapshot` data to the Risk Governor.

```
Executed Fill -> PortfolioLedger (Cash/Asset Entry) -> Position Projection -> Cost Basis & PnL -> ExitProtector -> RiskSnapshot Provider
```

## 2. Invariants & Bounds
- **Spot MVP LONG-Only**: Short selling, margin, futures, leverage, and naked SELLs are strictly prohibited.
- **Append-Only Ledger**: All cash debits, asset credits, fee debits, and realized PnL entries are recorded as immutable ledger entries.
- **No Direct Exchange Calls**: Exit triggers produce `PositionExitIntent`, passed to Exit Risk Validator for `ApprovedExitOrder` before Execution Engine simulated SELL.
- **Decimal Precision**: All currency, quantity, price, fee, and PnL calculations use `Decimal` with weighted average cost basis.
