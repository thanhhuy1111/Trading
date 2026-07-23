# DATABASE TRANSACTION EVIDENCE (F-04 atomicity)

Environment: Python 3.10.10; SQLAlchemy present; asyncpg 0.31.0 + alembic + psycopg2 installed
this round (declared project deps). **No PostgreSQL server** (no docker/initdb/psql); the lone
`:5432` is unknown-ownership and off-limits. PostgreSQL version: **N/A (not run)**.
Migration revision: `013_paper_runtime_persistence` (head).

## What is verified (design-level, no DB)
| Property | Command / Test | Result | Commit |
|---|---|---|---|
| Migration DDL emits atomically-usable schema | `alembic upgrade 012:013 --sql` (offline) | PASS — CREATE for all 7 `paper_*` tables + unique constraints + indexes | `3604dca` |
| Downgrade emits FK-safe drops | `alembic downgrade 013:012 --sql` (offline) | PASS — DROP in reverse/FK-safe order | `3604dca` |
| DDL compiles for postgresql dialect | `tests/unit/test_persistence_schema.py::test_all_tables_compile_for_postgres` | PASS | `3604dca` |
| One-transaction step order | `test_fill_commit_orchestration.py::test_happy_path_runs_all_steps_in_order_and_commits` | PASS — order == FILL_COMMIT_STEP_ORDER | `fdefaab` |
| Rollback on mid-transaction failure (no partial commit) | `...::test_failure_midway_rolls_back_and_does_not_commit` | PASS — `commit` never called, `rollback` called, later steps skipped | `fdefaab` |

## The atomic unit (packages/persistence/unit_of_work.py)
`FillCommitOrchestrator.commit_fill` runs, inside a single transaction, in this exact order:
`insert_fill → insert_ledger_entries → upsert_position → update_pnl_bucket → update_risk_state
→ append_journal → mark_order_filled → commit`. Any exception triggers `rollback()` and the
error is surfaced — so none of these states can exist: fill-without-ledger, ledger-without-fill,
position-without-cash-debit, PnL-updated-but-rolled-back, journal-for-uncommitted-txn.

## NOT verified (honest)
- No transaction ran against real PostgreSQL. The SQLAlchemy `FillTxnOps` implementation that
  binds these steps to `AsyncSession` + the `paper_*` tables is authored intent for the next
  round; the atomicity/rollback guarantees are verified only at the orchestration-logic level
  with a fake transaction object. **Status: IMPLEMENTED_NOT_VERIFIED on PostgreSQL.**
- Real fault-injection before/after commit and the process-restart drill require a disposable
  PostgreSQL (see `tests/integration/test_paper_durable_persistence.py`, currently skipped).
