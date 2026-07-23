# Service Level Objectives (SLO) & Error Budgets

## Target SLO Definitions
1. **Market Data Freshness**: 99.90% of public events received within 1000ms latency.
2. **Pipeline Success**: 99.50% of closed candles evaluated cleanly.
3. **Accounting Integrity**: 100.00% of portfolio audits passing 16 completeness checks.

## Error Budget Consumption
When current performance falls below the target percentage, error budget is consumed. Zero error budget remaining triggers alert rule notifications.
