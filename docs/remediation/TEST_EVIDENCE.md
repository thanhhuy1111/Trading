# TEST EVIDENCE

Environment: Python 3.10.10 (project targets 3.12 — not available here), Node v25.6.1 / npm 11.9.0.
`mypy`, `alembic`, `hypothesis`, `docker` NOT installed; Postgres/Redis unavailable.

| Command | Exit | Result | Notes |
|---|---|---|---|
| `python3 -m ruff check .` | 0 | **PASS** | "All checks passed!" |
| `python3 -m pytest tests/unit -q` | 0 | **PASS** | **118 passed** (baseline 109 + 9 new) |
| `cd apps/dashboard && npm run build` | 0 | **PASS** | tsc + vite, ~0.6s |
| `python3 -m pytest tests/integration -v` | — | **NOT RUN** | needs Postgres/Redis |
| `mypy .` | — | **NOT RUN** | not installed |
| `alembic upgrade/downgrade/upgrade` | — | **NOT RUN** | alembic not installed / no DB; no new migrations added this pass |
| `docker compose config` / `build` | — | **NOT RUN** | docker not installed |
| `npm run lint` / `npm test` (dashboard) | — | **NOT RUN** | scripts not defined in package.json (not added this pass) |

## New tests added (all pass)
- `tests/unit/test_decision_pipeline_e2e.py` — 3 tests: full chain → linked TradeIntent; warmup → NO_TRADE; critic never increases confidence in-chain.
- `tests/unit/test_pipeline_wiring.py` — 3 tests: paper uses `decision_service` & no fabricated literals; decision_service uses real components; no `65000` in agents/allocator.
- `tests/unit/test_execution_entry_cap.py` — 3 tests: BUY fill ≤ max entry with slippage; BUY clamped when ref==cap; SELL slippage respects limit.

No previously-passing test regressed (109 → 118).

## Requested test matrix — coverage status (honest)
- Architecture: production caller for the real pipeline (paper) ✅ (`test_pipeline_wiring`); ExecutionEngine caller ⚠️ (paper uses validation gate, not full engine); no fabricated intent in paper ✅ / backtest ❌ (still inline rule).
- Data: closed candle processed ✅; open candle ignored ✅ (guard added); duplicate ignored ✅ (existing). Out-of-order / gap→DEGRADED / DEGRADED-no-entry ⚠️ partial (DEGRADED blocks entry in paper; explicit gap tests not added).
- Agent pipeline: features→agents ✅; critic never increases ✅; missing expected return → NO_TRADE ✅; SHORT blocked ✅.
- Execution: BUY ≤ max entry ✅; non-zero slippage ✅; duplicate order idempotent ✅ (existing). Partial fill / retry / expiry / wrong-mode ❌ not added this pass.
- Accounting / isolation / recovery / backtest realism / security / dashboard: ❌ NOT addressed (see REMAINING_LIMITATIONS).
