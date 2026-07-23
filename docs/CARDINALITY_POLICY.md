# Cardinality Budget Policy

## Allowed Label Dimensions
To prevent Prometheus TSDB memory explosion, metric label keys are strictly restricted to the following low-cardinality set:
- `service`
- `environment`
- `exchange`
- `symbol`
- `timeframe`
- `component`
- `result`
- `reason_code`
- `status`
- `mode`

## Forbidden Keys
High-cardinality identifiers (such as `order_id`, `trade_id`, `user_id`, `client_order_id`, `correlation_id`, `timestamp`) MUST NEVER be included as metric labels. Violation raises `ValueError("CARDINALITY_POLICY_VIOLATION")`.
