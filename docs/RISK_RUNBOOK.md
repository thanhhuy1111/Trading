# Risk Runbook & Operating Procedures

## 1. Operating States
- **NORMAL**: Regular risk evaluation and intent sizing.
- **WARNING**: Reduced risk budget multiplier applied.
- **SOFT_STOP**: New entries blocked; existing position management allowed.
- **HARD_STOP**: All intents rejected; Kill Switch triggered.
- **MANUAL_HALT**: Operator halt active.

## 2. Recovery Procedure
To clear a `HARD_STOP` or `MANUAL_HALT`:
1. Inspect daily loss and drawdown metrics in the Risk Dashboard.
2. Confirm portfolio risk snapshot is fresh and valid.
3. Issue operator confirmation via `POST /risk/state/confirm-recovery`.
