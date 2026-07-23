# REMAINING LIMITATIONS (nothing hidden)

## Environment blockers (root cause of the C decision this round)
- **No Docker / docker compose.**
- **No Postgres client or driver** (`psql`, `asyncpg`, `psycopg2` all missing). A server is on
  `:5432` but is unusable and of unknown ownership — using/migrating it is forbidden.
- **No `alembic`** → migration cycle cannot run; no new migration was added.
- **No Redis** (`:6379` refused).
- **No `mypy`**; running Python 3.10, project targets 3.12.
- No network in tests → no live exchange feed.

Consequently the integration, migration, and docker acceptance gates could not run, and
F-03/F-04 cannot be marked verified. In-memory/SQLite substitutes were deliberately NOT used to
claim durability (explicitly disallowed).

## Findings still OPEN or PARTIAL
- **F-04 (OPEN):** durable persistence + real restart recovery not implemented (needs Postgres). Recovery is still a stub. This is the primary blocker to B.
- **F-02 (PARTIAL):** ingestion worker logic verified with a fake stream; live Binance public feed, DB-backed dedup, and `start_runtime` wiring not done/verifiable here.
- **F-03 (PARTIAL):** in-memory per-session isolation verified; durable per-session persistence and cross-process isolation pending (F-04). The global `portfolio_ledger` singleton still exists for legacy/default callers (routers, reconciliation).
- **F-05 (VERIFIED in-memory):** buckets are correct, but they are not persisted, so limits do not yet survive a restart (needs F-04).
- **F-06 (PARTIAL):** paper entries pass the validation gate but not the full ExecutionEngine; backtest still builds fills directly (at next open, capped).
- **F-07, F-10, F-11, F-12 (OPEN):** strategy validation, dashboard, backtest exit realism, and API auth were out of scope this round.

## Correctness caveats to keep in mind
- The expected-return value driving trades remains a transparent proxy (target × confidence), not a calibrated forecast — profitability is unproven (F-07).
- Backtest exits are still close-only (no intrabar high/low stop-through) (F-11).
- Ingestion dedup / sequence state is in-memory; a real restart would lose it until F-04 lands.
