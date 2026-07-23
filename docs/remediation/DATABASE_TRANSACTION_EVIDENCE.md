# DATABASE TRANSACTION EVIDENCE (F-04 atomicity)

## Round 4 — REAL PostgreSQL run

Environment: PostgreSQL 16.2 (disposable Docker container, `localhost:55432`), `alembic` head
`013_paper_runtime_persistence`. Command: `PAPER_DB_TEST_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/trading_db python3 -m pytest tests/integration/test_paper_durable_persistence.py -v`.

| Test | Result |
|---|---|
| `test_database_migration_cycle` | **PASS** — all 7 `paper_*` tables present |
| `test_fill_transaction_is_atomic_and_rolls_back` | **PASS** — fault injected in `update_risk_state`; after rollback: fill absent, ledger entries empty, position absent (no partial state) |

## What this proves (real, not simulated)
`SqlAlchemyFillTxnOps` (`packages/persistence/unit_of_work.py`) binds `FillCommitOrchestrator`'s
mandated step order — `insert_fill → insert_ledger_entries → upsert_position →
update_pnl_bucket → update_risk_state → append_journal → mark_order_filled → commit` — to real
`AsyncSession` operations against the `paper_*` tables. A `RuntimeError` injected mid-chain
causes `session.rollback()`; verified in a **separate** session afterwards that zero rows exist
for that fill across `paper_fills`, `paper_ledger_entries`, and `paper_positions` — genuinely no
partial-commit state, confirmed by querying the real database, not by inspecting in-memory
mocks.

## Commit
`ddbab2b fix: commit fills and accounting in one real PostgreSQL transaction`

## Status change
F-04 atomic-commit: **IMPLEMENTED_NOT_VERIFIED → RESOLVED_VERIFIED** (on PostgreSQL 16.2,
disposable).

## Remaining gap (honest)
The live `PaperPipeline.process_candle_close` runtime loop does **not yet** call
`FillCommitOrchestrator`/`SqlAlchemyFillTxnOps` — it still applies fills via the in-memory
`PositionManager.process_fill` path. The durable transaction mechanism is built and verified in
isolation (this document) but is not yet the active runtime path for live paper trading. Wiring
`PaperPipeline` to use it is the next actionable item (see REMAINING_LIMITATIONS.md).
