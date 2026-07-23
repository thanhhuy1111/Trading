# IMPLEMENTATION SUMMARY

Statuses: OPEN · PARTIAL · IMPLEMENTED_NOT_VERIFIED · RESOLVED_VERIFIED

## Round 4 — durable persistence, REAL PostgreSQL (decision moves C → B)
| Finding | Implementation | Unit evidence | Integration evidence | Status |
|---|---|---|---|---|
| (pre-existing) | Fixed migration chain: removed 7 duplicate table declarations from `001_initial_schema.py`; widened `alembic_version.version_num` in `env.py` | — | `alembic upgrade/downgrade/upgrade` PASS on real Postgres 16.2 | RESOLVED_VERIFIED |
| F-02 (candle dedup mechanism) | `ProcessedCandleRepository.claim` (unique-constraint race guard) | `test_persistence_schema` | `test_processed_candle_db_dedup`, `test_ingestion_resumes_from_high_water_mark` | RESOLVED_VERIFIED (mechanism); live worker not wired |
| F-03 (durable isolation) | Session-scoped repositories filtered by `session_id` | — | `test_two_sessions_are_durably_isolated` | RESOLVED_VERIFIED (mechanism); live runtime not wired |
| F-04 (atomic commit) | `SqlAlchemyFillTxnOps` binds `FillCommitOrchestrator` to real tables; `PositionManager.apply_fill_accounting` extracted for reuse | `test_fill_commit_orchestration` | `test_fill_transaction_is_atomic_and_rolls_back`, `test_fill_retry_is_idempotent`, `test_concurrent_fill_only_commits_once` | RESOLVED_VERIFIED |
| F-04 (recovery) | `PaperRecoveryService.recover_session_durable`: reconcile → rebuild or stay RECOVERY_REQUIRED | `test_recovery_reconciliation` | `test_restart_restores_exact_state`, `test_recovery_reconciles_and_transitions_to_ready`, `test_recovery_detects_ledger_mismatch_stays_recovery_required` | RESOLVED_VERIFIED |
| F-05 (durable buckets) | `PnLBucketRepository.add_realized_pnl` atomic upsert | `test_risk_pnl_windows` | `test_pnl_buckets_survive_restart`, `test_late_fill_updates_correct_bucket` | RESOLVED_VERIFIED (mechanism); live read-path not wired |
| F-07, F-10, F-11, F-12 | out of scope this round | — | — | OPEN |

## Files changed/added this round
- Fixed: `infra/migrations/versions/001_initial_schema.py` (removed 7 duplicate table
  declarations — user-approved), `infra/migrations/env.py` (widened `alembic_version` column).
- New: `packages/persistence/repositories.py`.
- Changed: `packages/common/database.py` (session factory), `packages/persistence/unit_of_work.py`
  (`SqlAlchemyFillTxnOps`), `packages/positions/manager.py` (extracted
  `apply_fill_accounting`), `packages/paper/recovery.py` (`recover_session_durable`),
  `tests/integration/test_paper_durable_persistence.py` (12 real tests, un-skipped).

## The honest remaining gap
All of the above is the **durable persistence mechanism**, proven correct against real
PostgreSQL. The **live paper-trading runtime** (`PaperPipeline.process_candle_close`,
`PaperIngestionWorker`) does not yet call this mechanism — it still operates purely in-memory.
Wiring the runtime to it is a plumbing task (connecting already-verified pieces), not a design
or correctness question, and is the top item for the next round.
