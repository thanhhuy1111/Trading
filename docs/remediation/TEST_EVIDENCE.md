# TEST EVIDENCE

Environment: Python 3.10.10 (target 3.12). Installed this round (declared deps): `asyncpg 0.31.0`,
`alembic`, `psycopg2`. Still absent: Docker, PostgreSQL server, Redis, `mypy`.

## Round 3 gate results
| Command | Exit | Result | Notes |
|---|---|---|---|
| `python3 -m ruff check .` | 0 | **PASS** | clean |
| `python3 -m pytest tests/unit -q` | 0 | **PASS** | **150 passed** (round-2: 137; +13 this round) |
| `python3 -m pytest tests/integration/test_paper_durable_persistence.py` | 0 | **8 skipped** | needs `PAPER_DB_TEST_URL` (no PostgreSQL) |
| `alembic history` / `heads` | 0 | **PASS** | `013` is head, chain intact |
| `alembic upgrade 012:013 --sql` / `downgrade 013:012 --sql` | 0 | **PASS** | offline DDL for all 7 tables + constraints + indexes |
| `alembic upgrade head` (online) | — | **NOT RUN** | no PostgreSQL server |
| `python3 -m pytest tests/integration` (full) | — | **NOT RUN** | needs Postgres/Redis |
| `mypy .` | — | **NOT RUN** | not installed |
| `cd apps/dashboard && npm run build` | 0 | **PASS** | no regression |

## New tests this round (all pass; no DB required)
- `tests/unit/test_persistence_schema.py` (4): postgres-dialect DDL compiles; idempotency unique constraints present; candle unique key columns; expected indexes present.
- `tests/unit/test_fill_commit_orchestration.py` (4): happy-path step order + commit; fast-path idempotent; mid-transaction failure → rollback, no commit; duplicate `fill_id` IntegrityError → idempotent, no double commit.
- `tests/unit/test_recovery_reconciliation.py` (5): clean → READY; cash imbalance; unlinked ledger entry; position mismatch; negative cash → RECOVERY_REQUIRED.
- `tests/integration/test_paper_durable_persistence.py` (8, **skipped**): migration cycle, atomic fill, fill retry idempotent, concurrent-fill-one-commit, candle DB dedup, durable isolation, restart restores state, PnL buckets survive restart.

No previously-passing test regressed (137 → 150).

## Requested test matrix coverage (honest)
- Migration cycle: ⚠️ offline SQL only; online NOT RUN.
- Atomic fill / rollback: ✅ logic (fake txn); PostgreSQL ❌.
- DB candle / order / fill idempotency: ✅ constraints + logic; PostgreSQL ❌.
- Concurrent duplicate: ✅ IntegrityError branch (simulated); real race ❌.
- Durable session isolation / process restart / PnL bucket restart / ingestion resume: ❌ NOT RUN (no PostgreSQL).
