# DB IDEMPOTENCY EVIDENCE (F-02 candle, F-04 order/fill)

Environment: as in DATABASE_TRANSACTION_EVIDENCE.md. PostgreSQL version: **N/A (not run)**.
Migration revision: `013_paper_runtime_persistence`.

## Idempotency guards defined in the schema (migration 013 / schema.py)
| Scope | Guard | Table |
|---|---|---|
| Candle (F-02) | `UNIQUE(session_id, symbol, timeframe, close_time)` = `uq_paper_candle_key` | `paper_processed_candles` |
| Order (F-04) | `UNIQUE(session_id, client_order_id)` = `uq_paper_order_client_id` | `paper_orders` |
| Fill (F-04) | `fill_id` PRIMARY KEY (globally unique) | `paper_fills` |
| Position (F-03) | `UNIQUE(session_id, symbol)` = `uq_paper_position_session_symbol` | `paper_positions` |
| PnL bucket (F-05) | `UNIQUE(session_id, bucket_type, bucket_start)` = `uq_paper_pnl_bucket` | `paper_pnl_buckets` |

## What is verified (design-level, no DB)
| Property | Test | Result | Commit |
|---|---|---|---|
| Unique constraints exist on the idempotency keys | `test_persistence_schema.py::test_idempotency_unique_constraints_present`, `::test_candle_unique_key_columns` | PASS | `3604dca` |
| Duplicate fill (already committed) → no-op replay, no mutation | `test_fill_commit_orchestration.py::test_fast_path_idempotent_when_already_committed` | PASS — `insert_fill` never attempted | `fdefaab` |
| Concurrent duplicate fill (unique-constraint IntegrityError) → single commit, idempotent result | `...::test_duplicate_fill_integrity_error_is_idempotent_not_double_commit` | PASS — `commit` not called, `rollback` called, `idempotent_replay=True` | `fdefaab` |

## Contract (packages/persistence/unit_of_work.py)
- Fast path: `fill_already_committed(fill_id)` → return idempotent result, mutate nothing.
- Race path: a second committer that loses the `fill_id` unique-constraint race catches
  `sqlalchemy.exc.IntegrityError`, rolls back, and returns an idempotent result — never a second
  cash debit / asset credit / position increase / fee / realized-PnL. The DB unique constraint is
  the last-resort guard (not an `if exists` check), exactly as required.

## NOT verified (honest)
- No real concurrent commit was executed against PostgreSQL. The "one commit wins" behaviour is
  verified only via a simulated `IntegrityError` in a fake ops object. **IMPLEMENTED_NOT_VERIFIED**
  on PostgreSQL. Real two-writer race + candle claim races are in the skipped integration suite.
- The runtime paper pipeline still uses the in-memory idempotency maps; switching the runtime to
  make PostgreSQL the source of truth is the remaining wiring step (needs a DB to verify).
