# Prometheus Metrics Catalog

## Domain Metrics Namespace: `trading_system_*`

| Metric Name | Type | Description | Allowed Labels |
|---|---|---|---|
| `trading_system_market_events_total` | Counter | Total market events ingested | `service`, `environment`, `exchange`, `symbol`, `result` |
| `trading_system_candles_closed_total` | Counter | Total closed candles processed | `service`, `symbol`, `timeframe` |
| `trading_system_agent_signals_total` | Counter | Total strategy signals generated | `service`, `symbol`, `status` |
| `trading_system_risk_evaluations_total` | Counter | Total Risk Governor evaluations | `service`, `result`, `reason_code` |
| `trading_system_orders_submitted_total` | Counter | Total orders submitted to simulator/paper | `service`, `exchange`, `symbol`, `mode` |
| `trading_system_fills_executed_total` | Counter | Total executed fills | `service`, `exchange`, `symbol` |
| `trading_system_paper_nav_quote` | Gauge | Current paper account Net Asset Value | `service`, `symbol` |
| `trading_system_paper_drawdown_pct` | Gauge | Current paper drawdown percentage | `service`, `symbol` |
