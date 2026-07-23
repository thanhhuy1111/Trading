# Execution Runbook & Operating Procedures

## 1. Monitoring Execution Reports
- Access FastAPI endpoint `GET /execution/reports` or React Dashboard `Execution Engine & Simulator` tab.
- Verify status is `FILLED` or `BLOCKED` with matching fingerprint.

## 2. Emergency Operations
- Global Risk State `HARD_STOP` immediately blocks all pre-execution validation gates.
- Disabled live adapter guarantees no external orders can be submitted under any circumstance.
