# RISK WINDOW EVIDENCE (F-05, F-13)

## Round 4 update — durable PnL buckets on REAL PostgreSQL

| Test | Result |
|---|---|
| `test_pnl_buckets_survive_restart` | **PASS** — BUY then SELL committed via the orchestrator; `paper_pnl_buckets` row for the DAILY bucket read back from Postgres shows positive realized PnL |
| `test_late_fill_updates_correct_bucket` | **PASS** — a fill with `executed_at` = yesterday, committed "late" (processed today), lands in **yesterday's** bucket; today's bucket is absent |

`PnLBucketRepository.add_realized_pnl` uses `INSERT ... ON CONFLICT (session_id, bucket_type,
bucket_start) DO UPDATE SET realized_pnl = realized_pnl + EXCLUDED.realized_pnl` — a single
atomic upsert, so concurrent fills into the same bucket cannot lose an update (no
read-modify-write race).

## Commits
`ddbab2b fix: commit fills and accounting in one real PostgreSQL transaction`,
`9c851ab test: verify durable persistence, idempotency and recovery on real PostgreSQL`

## Status change
F-05 durable PnL buckets: **PARTIAL (in-memory, round 2) → RESOLVED_VERIFIED (durable, on
PostgreSQL 16.2)**. F-13 unchanged (RESOLVED_VERIFIED since round 1).

## Remaining gap (honest)
The live `PaperPipeline`/`PositionManager.realized_pnl_window()` read path still reads from the
in-memory bucket dict (round 2), not from `paper_pnl_buckets`. The durable bucket table and its
atomic-upsert mechanism are proven correct (this document); wiring the Risk Governor's live read
path to the durable table is not yet done.
