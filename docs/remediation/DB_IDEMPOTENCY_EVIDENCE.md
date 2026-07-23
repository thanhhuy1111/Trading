# DB IDEMPOTENCY EVIDENCE (F-02 candle, F-04 order/fill)

## Round 4 — REAL PostgreSQL run

Environment: PostgreSQL 16.2 (disposable), migration head `013_paper_runtime_persistence`.

| Test | Result |
|---|---|
| `test_fill_retry_is_idempotent` | **PASS** — same `fill_id` submitted twice through the orchestrator; second call returns `idempotent_replay=True`, `committed=False`; exactly 1 row in `paper_fills`, exactly 3 ledger entries (not 6) |
| `test_concurrent_fill_only_commits_once` | **PASS** — two concurrent commits (`asyncio.gather`) racing on the SAME `fill_id`; exactly 1 committed, exactly 1 row in `paper_fills` afterwards |
| `test_processed_candle_db_dedup` | **PASS** — two concurrent claims (`asyncio.gather`) on the SAME `(session_id, symbol, timeframe, close_time)`; exactly 1 winner (the `uq_paper_candle_key` unique constraint decided it, not an `if exists` check) |
| `test_ingestion_resumes_from_high_water_mark` | **PASS** — a "new worker" querying `is_processed()` correctly sees prior candles as done; attempting to re-claim an already-claimed candle returns `None` (conflict) |

## What this proves
- **Order/fill idempotency**: `SqlAlchemyFillTxnOps.fill_already_committed` (fast path) and the
  `fill_id` primary key (last-resort race guard via `IntegrityError` → caught and converted to
  an idempotent result, never a raw 500) both verified with real concurrent PostgreSQL
  transactions — not simulated.
- **Candle idempotency**: `ProcessedCandleRepository.claim` uses
  `INSERT ... ON CONFLICT DO NOTHING RETURNING id` against the real `uq_paper_candle_key`
  constraint; under genuine `asyncio.gather` concurrency, exactly one of two simultaneous
  claims wins.

## Commits
`42a9a9f feat: add session-scoped persistence repositories`,
`ddbab2b fix: commit fills and accounting in one real PostgreSQL transaction`,
`9c851ab test: verify durable persistence, idempotency and recovery on real PostgreSQL`

## Status change
F-02 candle dedup (repository level) and F-04 order/fill idempotency:
**IMPLEMENTED_NOT_VERIFIED → RESOLVED_VERIFIED** (on PostgreSQL 16.2).

## Remaining gap (honest)
`PaperIngestionWorker` (`packages/paper/ingestion.py`) still uses an in-memory
`self._processed: Set[...]` for its own dedup, not yet wired to
`ProcessedCandleRepository.claim`. The DB-backed mechanism is proven correct in isolation
(above); connecting the live worker to it is the next actionable item.
