# TEST EVIDENCE

Environment: Python 3.10.10 (project targets 3.12 — unavailable). `mypy`, `alembic`,
`asyncpg`/`psycopg2`, Redis, Docker all ABSENT. Postgres on :5432 present but unusable
(no driver/client) and must not be touched.

## Round 2 gate results
| Command | Exit | Result | Notes |
|---|---|---|---|
| `python3 -m ruff check .` | 0 | **PASS** | clean |
| `python3 -m pytest tests/unit -q` | 0 | **PASS** | **137 passed** (round-1: 118; +19 this round) |
| `cd apps/dashboard && npm run build` | 0 | **PASS** | tsc + vite (~0.6s), no regression |
| `python3 -m pytest tests/integration -v` | — | **NOT RUN** | needs Postgres/Redis |
| `mypy .` | — | **NOT RUN** | not installed |
| `alembic upgrade/downgrade/upgrade` | — | **NOT RUN** | alembic absent / no usable DB; no new migrations added |
| `docker compose config` / `build` / `up` | — | **NOT RUN** | docker absent |

## New tests this round (all pass)
- `tests/unit/test_paper_ingestion_worker.py` (8): open ignored, dedup, out-of-order, gap→backfill→RUNNING, unrecoverable gap→RECOVERY_REQUIRED, clock-skew degrade, clean start/stop, DEGRADED-blocks-entry vs RUNNING-opens-entry.
- `tests/unit/test_session_isolation_inmemory.py` (3): two-session independent cash/positions/NAV, per-session ledgers via paper pipeline, ExitProtector writes to injected manager not global.
- `tests/unit/test_risk_pnl_windows.py` (5): daily/weekly reset, late fill to past bucket, timezone-independent bucketing, independent per-manager buckets.
- `tests/unit/test_backtest_decision_wiring.py` (3): engine source uses decision_service (no fabrication), decision determinism/fingerprint stability, rise-then-fall backtest opens+exits a real round-trip.

No previously-passing test regressed (118 → 137).

## Test matrix coverage (honest)
- Ingestion (open/closed/dedup/out-of-order/gap→DEGRADED/DEGRADED-blocks-entry/backfill→RUNNING/clean-cancel): ✅ unit (fake stream). Reconnect-no-duplicate ✅ (dedup + seq). Live feed ❌.
- Session isolation (A cash⟂B, positions⟂, exit⟂, independent NAV): ✅ in-memory. Cross-process ❌.
- Persistence (fill+ledger+position one transaction; rollback; unique constraints; concurrent dedup): ❌ NOT RUN (no DB) — F-04 OPEN.
- Recovery (restart restores state; replay no-op; corrupt→RECOVERY_REQUIRED): ❌ NOT RUN (no DB) — F-04 OPEN.
- PnL windows (UTC midnight / ISO week / late event / restart / isolation / hard-stop): ✅ except "restart" (needs persistence).
- Shared pipeline (paper uses DecisionService; backtest uses DecisionService; no fabricated intent; same-input same-fingerprint): ✅.
