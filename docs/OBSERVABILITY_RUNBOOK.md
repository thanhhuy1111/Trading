# Operational Observability Runbook

## Market Stream Disconnected
- **Symptom**: Alert `MarketDataStreamDisconnected` active or public WebSocket stream dropped.
- **Action**: Check network connectivity; inspect `paper_market_runtime` logs; trigger REST backfill to recover sequence gap.

## Risk Hard Stop Active
- **Symptom**: Alert `RiskGovernorKillSwitchActive` triggered.
- **Action**: Verify max drawdown or daily loss limits; inspect Risk Governor logs; acknowledge incident; resolve underlying cause before resetting paper session.

## Position Reconciliation Failure
- **Symptom**: Alert `ExecutionReconciliationFailure` active.
- **Action**: Run 16 completeness checks on portfolio ledger; verify subledger transactions match execution fills; review audit logs.
