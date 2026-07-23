# Backtest Engine Runbook & Operating Procedures

## 1. Registration & Execution Workflow
1. Register dataset via `POST /backtests/datasets/register`.
2. Create backtest session via `POST /backtests`.
3. Launch historical simulation via `POST /backtests/{session_id}/run`.
4. Monitor execution metrics and equity curve via REST API or Dashboard.
