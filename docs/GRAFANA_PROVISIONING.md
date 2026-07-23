# Grafana Provisioning Guide

## Provisioning Setup
Grafana data sources and dashboards are provisioned via `infra/grafana/`:
- `datasources.yml`: Configures Prometheus datasource (`http://prometheus:9090`).
- `dashboards.yml`: Loads dashboard definitions from `/var/lib/grafana/dashboards`.
- `overview.json`: Standardized system overview dashboard.

## Folder Hierarchy
1. `00 System Overview`
2. `10 Market Data`
3. `20 Strategy and Governance`
4. `30 Risk`
5. `40 Execution`
6. `50 Portfolio`
7. `60 Backtest`
8. `70 Paper Trading`
9. `80 Infrastructure`
10. `90 Incidents and SLO`
