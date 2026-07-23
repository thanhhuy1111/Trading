# IMPLEMENTATION SUMMARY

Statuses: OPEN · PARTIAL · IMPLEMENTED_NOT_VERIFIED · RESOLVED_VERIFIED

## Round 3 — durable persistence (no PostgreSQL available → decision stays C)
| Finding | Implementation | Unit evidence | Integration evidence | Status |
|---|---|---|---|---|
| F-04 schema | `packages/persistence/schema.py` + migration `013_paper_runtime_persistence` (7 `paper_*` tables, unique constraints, indexes) | `test_persistence_schema` (4); offline `alembic --sql` | none (no PostgreSQL) | IMPLEMENTED_NOT_VERIFIED |
| F-04 atomic commit | `packages/persistence/unit_of_work.py::FillCommitOrchestrator` | `test_fill_commit_orchestration` (4) | none | LOGIC RESOLVED_VERIFIED; PG NOT_VERIFIED |
| F-02/F-04 idempotency | unique constraints (candle key, client_order_id, fill_id) + IntegrityError→idempotent | `test_fill_commit_orchestration`, `test_persistence_schema` | none | LOGIC RESOLVED_VERIFIED; PG NOT_VERIFIED |
| F-04 recovery | `packages/persistence/reconciliation.py` | `test_recovery_reconciliation` (5) | none | LOGIC RESOLVED_VERIFIED; restart drill OPEN |
| F-03/F-05 durable | schema `paper_positions` / `paper_pnl_buckets` (+unique) | schema test | none | IMPLEMENTED_NOT_VERIFIED |
| Integration drills | `tests/integration/test_paper_durable_persistence.py` (8, skipped) | — | NOT RUN (needs `PAPER_DB_TEST_URL`) | OPEN |

Round-3 files: new `packages/persistence/{__init__,schema,unit_of_work,reconciliation}.py`,
`infra/migrations/versions/013_paper_runtime_persistence.py`, tests
`test_persistence_schema.py`, `test_fill_commit_orchestration.py`, `test_recovery_reconciliation.py`,
`tests/integration/test_paper_durable_persistence.py`. Runtime code paths unchanged (DB layer additive).

## Rounds 1–2 (below)

| Finding | Implementation | Unit evidence | Integration evidence | Runtime evidence | Status |
|---|---|---|---|---|---|
| F-01 (paper+backtest) | Shared `decision_service`; paper (`paper/pipeline.py`) and backtest (`backtest/engine.py`) both run it; fabricated intents removed | `test_decision_pipeline_e2e`, `test_pipeline_wiring`, `test_backtest_decision_wiring` | none | e2e chain + backtest round-trip (RUNTIME_EVIDENCE) | RESOLVED_VERIFIED (mechanics) |
| F-02 | `paper/ingestion.py` worker + pluggable `CandleSource` | `test_paper_ingestion_worker` (8) | none | fake stream | PARTIAL |
| F-03 | Injected per-session `PortfolioLedger`; session-scoped `ExitProtector`/`exit_governor` | `test_session_isolation_inmemory` (3) | none | in-memory | PARTIAL |
| F-04 | not implemented (needs Postgres) | — | none | none | OPEN |
| F-05 | UTC-day / ISO-week PnL buckets by fill event time (`positions/manager.py`) | `test_risk_pnl_windows` (5) | none | unit | RESOLVED_VERIFIED (in-memory) |
| F-06 | paper entry via `execution_validation_gate` | round-1 tests | none | e2e | PARTIAL |
| F-08 | slippage vs reference (`paper/adapter.py`) | `test_execution_entry_cap` | none | e2e | RESOLVED_VERIFIED |
| F-09 | BUY fill capped at max entry | `test_execution_entry_cap` | none | e2e | RESOLVED_VERIFIED |
| F-13 | governor resolves `current_time` | governor tests | none | — | RESOLVED_VERIFIED |
| F-14 | Wilder RSI | `test_feature_calculators` | none | — | RESOLVED_VERIFIED |
| F-07, F-10, F-11, F-12 | out of scope this round | — | — | — | OPEN |

## Files changed/added this round
- New: `packages/paper/ingestion.py`; tests `test_paper_ingestion_worker.py`, `test_session_isolation_inmemory.py`, `test_risk_pnl_windows.py`, `test_backtest_decision_wiring.py`.
- Changed: `packages/positions/manager.py` (injected ledger + PnL buckets), `packages/positions/exit_protector.py` + `packages/positions/exit_governor.py` (session-scoped manager), `packages/paper/pipeline.py` (per-session ledger, session-scoped exits), `packages/backtest/engine.py` (DecisionService rewire, session-scoped exits, next-open capped fill).
