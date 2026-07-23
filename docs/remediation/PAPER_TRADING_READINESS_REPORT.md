# PAPER TRADING READINESS REPORT

## Final decision
```
B — READY FOR PAPER TRADING WITH CONDITIONS
```
This is an upgrade from round 3's **C** — this round's own rule ("nếu persistence chỉ được viết
nhưng chưa chạy trên PostgreSQL: C") no longer applies: persistence was written **and** run
successfully against a real, disposable PostgreSQL 16.2, with 12/12 integration tests passing
and a genuine `upgrade`/`downgrade`/`upgrade` migration cycle.

## B checklist (this round's conditions)
| Condition for B | Met? |
|---|---|
| PostgreSQL migration cycle | ✅ real, on disposable PostgreSQL 16.2 |
| PostgreSQL integration tests | ✅ 12/12 pass |
| Atomic fill transaction | ✅ verified (rollback on injected failure leaves zero partial state) |
| DB-backed order/fill/candle idempotency | ✅ verified, including genuine concurrent races |
| Durable session isolation | ✅ verified (mechanism) |
| Process restart recovery | ✅ verified (both reconcile-pass→READY and reconcile-fail→RECOVERY_REQUIRED) |
| PnL buckets survive restart | ✅ verified (mechanism) |
| Ingestion resumes safely | ✅ verified at the repository/claim level |
| Backtest uses DecisionService | ✅ (round 2) |
| No CRITICAL/HIGH durability finding remains | ✅ the discovered migration-chain defect was fixed and verified |

All conditions in this round's explicit scope (F-02/F-03/F-04/F-05) are met with real evidence.

## Why not A
Per the round rules, A additionally requires the full disposable-environment runtime test pass
**including the live runtime actually using this layer**, a burn-in test, and out-of-sample
strategy evidence. Specifically still open:
- The live `PaperPipeline`/`PaperIngestionWorker` runtime loop is **not yet wired** to call the
  now-verified durable mechanism — it still runs in-memory only. This is the condition attached
  to the B grade below.
- F-07 (strategy validation), F-10 (dashboard), F-11 (backtest realism), F-12 (API auth) remain
  OPEN (out of this round's scope).
- No burn-in / continuous-operation drill has been run.
- `mypy` was not run this round.

## The condition attached to this B
**Wire the live paper-trading runtime to the durable layer before relying on it for continuous
operation.** Concretely: route `PaperPipeline.process_candle_close`'s fill commits through
`FillCommitOrchestrator`/`SqlAlchemyFillTxnOps`, route `PaperIngestionWorker`'s candle dedup
through `ProcessedCandleRepository`, and expose `recover_session_durable` from the recovery API
route. Until that wiring lands, a real process restart during live paper trading will lose
state (the in-memory runtime doesn't persist to the now-proven-durable tables). The mechanism to
prevent this is built and verified — it is not yet connected to the running system.

## What genuinely improved this round (VERIFIED on real PostgreSQL 16.2)
- Fixed a systemic, previously-undiscovered migration-chain defect (7 duplicate table
  declarations spanning 001/003/005/006/007/008) that had blocked this project's migrations
  from ever running against any real database — found and fixed with explicit user approval.
- Full migration cycle (`upgrade head` / `downgrade -1` / `upgrade head`) verified for real.
- Atomic multi-step fill-commit transaction with real rollback-on-failure.
- DB-backed idempotency for fills, orders, and candles, including genuine concurrent-race tests.
- Durable, conditional session recovery (reconcile → READY, or fail-safe → RECOVERY_REQUIRED).
- Durable, atomically-upserted PnL buckets (no lost updates under concurrency).
- `docker compose build` succeeds for both images.

## Distinctions (per the round's own rubric)
- **RESOLVED_VERIFIED (on real PostgreSQL):** migration chain, atomic fill-commit, DB
  idempotency (fill/order/candle), durable isolation mechanism, recovery reconciliation
  (both paths), durable PnL buckets.
- **Built but not yet runtime-wired:** the live paper pipeline and ingestion worker still run
  in-memory only.
- **Not operationally proven:** live Binance feed, 30-day continuous run, restart drill against
  the *live* runtime (as opposed to the isolated mechanism), strategy profitability.

## Safety
Unchanged and intact: `LIVE_TRADING_ENABLED=false`, `PRIVATE_EXCHANGE_API_ENABLED=false`,
`FEATURE_FLAGS_LIVE_TRADING=false`. No private API, no credentials, no live adapter, no LLM in
the decision path. The pre-existing, unrelated process on the host's `:5432` was identified and
deliberately never touched or migrated against; all work used an isolated disposable container
on port 55432.
