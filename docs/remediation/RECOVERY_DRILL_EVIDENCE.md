# RECOVERY DRILL EVIDENCE (F-04)

| Finding | Implementation | Unit evidence | Integration evidence | Runtime evidence | Status |
|---|---|---|---|---|---|
| F-04 | NOT implemented this pass | — | NONE | NONE | **OPEN (infra-blocked)** |

## Why this is OPEN, not verified
Real restart recovery requires durable state in PostgreSQL (orders, fills, ledger entries,
positions, risk state, processed-candle high-water mark) plus a migration and DB-backed
idempotency. This environment has:
- no `docker` / `docker compose`,
- no Postgres **client or driver** (`psql`, `asyncpg`, `psycopg2` all missing),
- no `alembic`,
- no Redis (port 6379 refused).

A Postgres server is listening on `:5432`, but with no driver/client and unknown ownership it
**must not** be used — running migrations against an unknown/possibly-production database is
explicitly forbidden this round. No disposable Postgres could be provisioned (no server binaries).

Per this round's §9 and §15, without disposable Postgres/Redis the durable-recovery gates
cannot be run, F-04 cannot be marked verified, and the final decision stays **C**. Fabricating a
recovery pass with an in-memory/SQLite substitute is explicitly disallowed, so it was not done.

## What remains to close F-04 (next round, with a DB)
1. New Alembic migration for the persistence tables + unique constraints (`fill_id`;
   `session_id+client_order_id`; `session_id+symbol+timeframe+close_time`; `decision_id`;
   `ledger_entry_id`) with `upgrade`/`downgrade` and an upgrade/downgrade/upgrade cycle.
2. Repository + transaction-orchestration layer: one fill → (fill, ledger entries, position,
   PnL bucket, risk state, journal, outbox) committed atomically or rolled back.
3. `recover_session`: load committed state, reconcile `NAV = cash + Σ(qty × mark)`, verify no
   unlinked fills / ledger imbalance / unknown orders, rebuild runtime context, and only then
   `RECOVERY_REQUIRED → READY`; otherwise stay `RECOVERY_REQUIRED` + incident.
4. Fault-injection + process-restart integration tests on a disposable Postgres proving no
   duplicate fill, no double fee/position, and identical pre/post-restart state.
