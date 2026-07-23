# Position Manager Runbook & Operating Procedures

## 1. Portfolio Snapshot Monitoring
- Access `GET /portfolio/snapshots/latest` or React Dashboard `Positions & Portfolio Ledger` tab.
- Verify NAV, Cash, Asset Market Value, and Drawdown %.

## 2. Emergency Safeguards
- Position Manager cannot execute SELL orders directly.
- All exits must pass Exit Risk Validator as `reduce_only=True` SELL orders.
