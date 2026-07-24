# Phase 11 — Shadow Trading

## Status

**COMPLETE**

## Delivered

- Every recorded proposal auto-schedules its persisted prediction horizon (one bar by
  default, matching the approved XGBoost contract) based on its timeframe.
- Scheduler kill switch, locked idempotent scheduling/evaluation and append-only outcome
  transition history.
- Runtime and historical replay stores have incompatible explicit modes.
- Evaluation requires a complete, contiguous, correctly aligned closed Binance public candle
  window ending at the horizon; future/out-of-source/misaligned records are excluded.
- Missing/incomplete/transient-provider windows remain `PENDING` for retry. Permanent lineage
  corruption fails safely without affecting other jobs.
- Persisted horizon close, actual directional label, prediction correctness, barrier/timeout
  return and costs.
- Point-in-time reports reconstruct historical pending/final state and report actual-label,
  directional and per-agent correctness counts without treating profitability as accuracy.

## Verification

- Shadow + acceptance + domain focused tests: 34 passed.
- Full pytest: 578 passed, 12 skipped, 1 known Alembic failure.
- Ruff/diff clean; mypy remains baseline.
- Independent review: no remaining CRITICAL/HIGH/MEDIUM findings after fixes.

No order adapter, private API or live-trading path is imported or called.
