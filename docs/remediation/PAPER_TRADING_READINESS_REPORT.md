# PAPER TRADING READINESS REPORT

## Final decision
```
C — NOT READY FOR PAPER TRADING
```
Round 3 built the durable-persistence foundation and verified its DESIGN and LOGIC, but the
round's own rule (§19) is explicit: *"Nếu persistence chỉ được viết nhưng chưa chạy trên
PostgreSQL: C."* No PostgreSQL server was available, so the migration cycle, integration drills,
and restart recovery could not run. Decision stays **C**.

## Why not B (this round's B checklist)
| Condition for B | Met? |
|---|---|
| PostgreSQL migration cycle | ❌ NOT RUN (no server); offline `--sql` only |
| PostgreSQL integration tests | ❌ NOT RUN (skipped skeleton) |
| Atomic fill transaction | ⚠️ LOGIC verified (fake txn); PostgreSQL NOT verified |
| DB-backed order/fill/candle idempotency | ⚠️ constraints defined + logic verified; PostgreSQL NOT verified |
| Durable session isolation | ❌ schema ready; PostgreSQL drill NOT RUN |
| Process restart recovery | ⚠️ reconciliation logic verified; end-to-end drill NOT RUN |
| PnL buckets survive restart | ❌ durable schema ready; NOT RUN |
| Ingestion resumes safely | ❌ NOT RUN |
| No CRITICAL/HIGH durability finding remains | ❌ F-04 durability still unverified |

## Genuinely delivered this round (design/logic verified, no DB)
- Durable `paper_*` schema + Alembic migration `013` (head); DDL compiles for postgres; offline `--sql` upgrade/downgrade validated.
- Idempotency unique constraints on candle key, `(session_id, client_order_id)`, `fill_id`, position, PnL bucket.
- `FillCommitOrchestrator`: single-transaction step order, rollback-on-failure (no partial commit), duplicate→idempotent (no double mutation) — unit-verified via a fake transaction.
- `reconcile_session`: derives cash/positions from the ledger and flags imbalance / unlinked fill / position mismatch / negative cash — unit-verified.
- 150 unit tests pass (round-2: 137 → +13); ruff clean; frontend builds.

## Distinctions
- **RESOLVED_VERIFIED (logic/design):** fill-commit orchestration, idempotency branching, reconciliation, schema DDL/constraints, offline migration SQL.
- **IMPLEMENTED_NOT_VERIFIED (needs PostgreSQL):** the SQLAlchemy binding of the orchestrator to real tables, the online migration cycle, durable isolation, restart recovery, durable PnL buckets, DB candle dedup.
- **OPEN:** wiring the runtime to make PostgreSQL the source of truth; F-07/F-10/F-11/F-12.

## The single blocker to B
A disposable PostgreSQL (ideally via the repo's `docker compose`, or a throwaway local DB with a
dedicated test database). With it, the next round runs: alembic cycle, the `SqlAlchemyFillTxnOps`
binding, and the integration drills in `tests/integration/test_paper_durable_persistence.py`
(gated by `PAPER_DB_TEST_URL`).

## Safety
Unchanged and intact: `LIVE_TRADING_ENABLED=false`, `PRIVATE_EXCHANGE_API_ENABLED=false`,
`FEATURE_FLAGS_LIVE_TRADING=false`. No private API, no credentials, no live adapter, no LLM in the
decision path. The unknown `:5432` server was deliberately never touched.
