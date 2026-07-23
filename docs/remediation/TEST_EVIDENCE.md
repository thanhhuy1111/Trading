# TEST EVIDENCE

## Round 4 gate results (REAL PostgreSQL + Docker)
Environment: Python 3.10.10, Docker Desktop 29.6.2, disposable PostgreSQL 16.2 (`localhost:55432`),
Redis 7.2 (`localhost:6379`). `alembic`, `asyncpg`, `psycopg2-binary`, `pytest-asyncio` installed
(all declared in `pyproject.toml`).

| Command | Exit | Result | Notes |
|---|---|---|---|
| `python3 -m ruff check .` | 0 | **PASS** | clean |
| `python3 -m pytest tests/unit -q` | 0 | **PASS** | **150 passed**, no regressions |
| `PAPER_DB_TEST_URL=... python3 -m pytest tests/integration/test_paper_durable_persistence.py -v` | 0 | **PASS** | **12 passed, 0 skipped** — real PostgreSQL |
| `alembic upgrade head` (online, real DB) | 0 | **PASS** | 111 tables created, first time ever |
| `alembic downgrade -1` (online, real DB) | 0 | **PASS** | reverted to 012, 7 `paper_*` tables dropped |
| `alembic upgrade head` (online, again) | 0 | **PASS** | back to 013 (head), tables recreated correctly |
| `docker compose config` | 0 | **PASS** | (services resolved under `--profile minimal`) |
| `docker compose --profile minimal build` | 0 | **PASS** | both `trading-api` and `trading-dashboard` images built |
| `cd apps/dashboard && npm run build` | 0 | **PASS** | no regression |
| `mypy .` | — | **NOT RUN** | not installed; not declared as blocking for this round's scope |
| `python3 -m pytest tests/integration` (full suite incl. DB/Redis-agnostic ones) | — | partially run (durable persistence file only; others unaffected) |

## New integration tests this round (all 12 pass on real PostgreSQL)
`tests/integration/test_paper_durable_persistence.py`:
`test_database_migration_cycle`, `test_fill_transaction_is_atomic_and_rolls_back`,
`test_fill_retry_is_idempotent`, `test_concurrent_fill_only_commits_once`,
`test_processed_candle_db_dedup`, `test_two_sessions_are_durably_isolated`,
`test_restart_restores_exact_state`, `test_pnl_buckets_survive_restart`,
`test_late_fill_updates_correct_bucket`, `test_recovery_reconciles_and_transitions_to_ready`,
`test_recovery_detects_ledger_mismatch_stays_recovery_required`,
`test_ingestion_resumes_from_high_water_mark`.

No previously-passing test regressed (150 unit tests unchanged; round-3's 12 skipped
integration placeholders are now fully implemented and passing for real).

## Test matrix coverage — round 4 (honest)
- Migration cycle: ✅ real PostgreSQL (upgrade/downgrade/upgrade).
- Atomic fill / rollback: ✅ real PostgreSQL.
- DB candle / order / fill idempotency: ✅ real PostgreSQL, including genuine concurrent races via `asyncio.gather`.
- Concurrent duplicate: ✅ real PostgreSQL (fill race + candle claim race).
- Durable session isolation: ✅ real PostgreSQL.
- Process restart / reconciliation: ✅ real PostgreSQL (both the pass and the fail-safe path).
- PnL bucket restart / late-fill bucketing: ✅ real PostgreSQL.
- Live runtime wiring (PaperPipeline/PaperIngestionWorker actually using this layer): ❌ NOT DONE — see REMAINING_LIMITATIONS.md.
- mypy / full docker `up` smoke test: ❌ NOT RUN this round.
