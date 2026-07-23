# INGESTION RUNTIME EVIDENCE (F-02)

| Finding | Implementation | Unit evidence | Integration evidence | Runtime evidence | Status |
|---|---|---|---|---|---|
| F-02 | `packages/paper/ingestion.py` — `PaperIngestionWorker` + pluggable `CandleSource` | `tests/unit/test_paper_ingestion_worker.py` (8 tests, all pass) | NONE (no Redis/DB, no live feed) | Fake-stream only | **PARTIAL** (worker logic verified; live feed + DB dedup blocked) |

## Verified with a fake, in-process stream (no network)
- Open candle ignored (`is_closed == False` → `IGNORED_OPEN`).
- Closed candle processed exactly once; duplicate `(symbol, tf, close_time)` → `DUPLICATE`.
- Out-of-order sequence → `OUT_OF_ORDER` (quarantined, not processed).
- Sequence gap → runtime `DEGRADED` → public backfill of missing seqs → processed in order → back to `RUNNING` (`GAP_RECOVERED`).
- Unrecoverable gap → `RECOVERY_REQUIRED`.
- Clock skew beyond 5s → `SKEW_DEGRADED`, candle not processed (fail-closed).
- `start()` spawns a single task; `stop()` cancels cleanly (no orphan; `state == STOPPED`, `_task is None`).
- End-to-end: a **DEGRADED** session does **not** open new entries even with a warm uptrend buffer, while a **RUNNING** session with identical candles **does** open a position (`test_degraded_session_blocks_new_entries_end_to_end`).

## NOT verified here (honest)
- No connection to a live Binance public WebSocket/REST feed was exercised (no network in tests). A live `CandleSource` is described but not implemented against the exchange this pass.
- Dedup / sequence state is in-memory. DB-backed idempotency (unique on `session_id, symbol, timeframe, close_time`) is Phase B and is BLOCKED (no Postgres).
- `start_runtime()` is not yet wired to spawn this worker with a live source in the FastAPI route; that wiring needs an async runtime + feed and was not runtime-verifiable here.
