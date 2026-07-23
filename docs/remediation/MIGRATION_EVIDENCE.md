# MIGRATION EVIDENCE

## Round 4 — REAL PostgreSQL run (first time ever)

Environment: Docker Desktop 29.6.2 + Compose v5.3.1. Disposable container `postgres:16.2-alpine`
run directly (bypassing the repo's `docker compose` port mapping to avoid any collision with an
unrelated, unknown-ownership process already bound to host `:5432` — never touched), published
on host port **55432**. `alembic`, `asyncpg`, `psycopg2-binary` installed (all declared in
`pyproject.toml`).

### Pre-existing defect discovered and fixed (with explicit user approval)
This migration chain (001→012, inherited from prior milestones) had **never been executed
against a real PostgreSQL database before** — not in this remediation's 3 prior rounds (no DB
available), and apparently not in the project's history either. Running it for the first time
surfaced two latent, pre-existing bugs:

1. **Duplicate table declarations.** `001_initial_schema.py` declared 7 tables (`exchanges`,
   `symbols`, `trade_intents`, `risk_decisions`, `fills`, `positions`, `portfolio_snapshots`)
   with an early draft schema; each was later redeclared with the real/complete schema by a
   milestone migration (003, 005, 006, 007, 008 respectively) — same table name, different
   columns. `alembic upgrade head` therefore always failed with `DuplicateTableError` on any
   fresh database. **Fixed** (user-approved) by removing the 7 duplicate declarations from
   `001_initial_schema.py`'s `upgrade()`/`downgrade()`; the milestone migrations remain the sole
   owners, unchanged.
2. **`alembic_version.version_num` too narrow.** Alembic's default column is `VARCHAR(32)`;
   revision id `007_execution_engine_and_simulator` is 34 characters. **Fixed** by widening the
   column to `VARCHAR(255)` idempotently in `infra/migrations/env.py` (Alembic's own environment
   script — not the content of any versioned migration file).

New migration **`013_paper_runtime_persistence`** (revises `012_security_hardening`, now head)
adds the session-scoped durable paper tables from round 3. Unchanged.

### Real results
| Command | Result |
|---|---|
| `alembic upgrade head` (fresh DB) | **PASS** — all 13 migrations (001→013) applied; 111 tables created |
| `alembic downgrade -1` | **PASS** — reverted to `012_security_hardening`; the 7 `paper_*` tables from 013 dropped |
| `alembic upgrade head` (again) | **PASS** — back to `013_paper_runtime_persistence` (head); all 7 `paper_*` tables + columns + indexes recreated correctly |
| PostgreSQL version | **16.2** (`postgres:16.2-alpine`) |

This is genuine, first-time-ever, real-database verification of the entire migration chain —
not offline `--sql` generation (round 3's evidence), an actual `upgrade`/`downgrade`/`upgrade`
cycle executed against a live server.
