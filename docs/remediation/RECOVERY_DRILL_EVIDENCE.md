# RECOVERY DRILL EVIDENCE (F-04)

| Aspect | Implementation | Unit evidence | Integration evidence | Status |
|---|---|---|---|---|
| Reconciliation logic | `packages/persistence/reconciliation.py` | `tests/unit/test_recovery_reconciliation.py` (5) | none | RESOLVED_VERIFIED (logic only) |
| Durable persistence + restart drill | schema/migration 013 + `unit_of_work.py` authored | schema/orchestration unit tests | none (no PostgreSQL) | IMPLEMENTED_NOT_VERIFIED |
| Process-restart equality drill | integration skeleton (skipped) | — | NOT RUN | OPEN |

## Verified this round (pure logic, no DB)
`reconcile_session(...)` derives cash and asset quantities from ledger rows and compares them to
materialized state:
- clean state → `passed=True` → `recovery_status == "READY"`;
- cash imbalance → `CASH_IMBALANCE` → `RECOVERY_REQUIRED`;
- ledger row referencing a non-persisted fill → `UNLINKED_LEDGER_ENTRY`;
- position quantity mismatch → `POSITION_MISMATCH`;
- negative derived cash → `NEGATIVE_CASH`.

This is the decision core the recovery service will use: only promote `RECOVERY_REQUIRED → READY`
when reconciliation passes, else stay `RECOVERY_REQUIRED` + incident.

## NOT verified (infra-blocked)
The end-to-end restart drill (§13 of the round spec) — persist a fill, destroy the runtime,
recreate it, recover, replay the same candle/order/fill, and assert
`snapshot_before == snapshot_after` with zero duplicate fills/ledger/cash/position/PnL deltas —
requires a disposable PostgreSQL, which is absent (no docker/initdb/psql; `:5432` off-limits).
It is encoded as skipped tests in `tests/integration/test_paper_durable_persistence.py`
(`test_restart_restores_exact_state`, `test_pnl_buckets_survive_restart`, …) and must be run on
real PostgreSQL before F-04 can be marked verified. Until then the decision stays **C**.
