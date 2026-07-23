# RECOVERY DRILL EVIDENCE (F-04)

## Round 4 — REAL PostgreSQL run

Environment: PostgreSQL 16.2 (disposable, `localhost:55432`), migration head `013_paper_runtime_persistence`.

| Test | Result |
|---|---|
| `test_restart_restores_exact_state` | **PASS** — a fill is committed, the in-memory `PositionManager` is discarded (`del pm_before`), fresh repository reads + `reconcile_session` against PostgreSQL reproduce the exact same cash delta, position quantity (0.1), and average entry price as the original in-memory state |
| `test_recovery_reconciles_and_transitions_to_ready` | **PASS** — `PaperRecoveryService.recover_session_durable` loads fills/ledger/positions from Postgres, reconciles, rebuilds a fresh `PositionManager` with the correct position (`0.1` BTC), and transitions the session `RECOVERY_REQUIRED → READY` |
| `test_recovery_detects_ledger_mismatch_stays_recovery_required` | **PASS** — after committing a fill, the `paper_positions.quantity` row is corrupted directly (simulating drift/corruption: set to `999.0`); recovery detects `POSITION_MISMATCH`, `result.passed == False`, returns `rebuilt_pm=None`, and the session **stays** `RECOVERY_REQUIRED` (never silently promoted) |

## Recovery flow implemented (`packages/paper/recovery.py::recover_session_durable`)
```
Load fills/ledger entries/positions from PostgreSQL for session_id
→ derive cash (initial_cash − Σdebits + Σcredits) and asset quantities from the ledger
→ reconcile_session(...) — unlinked-fill, cash-imbalance, position-mismatch, negative-cash checks
→ PASS: rebuild in-memory PortfolioLedger (cash/asset balances, processed_fill_ids) and
        PositionManager (positions dict) purely from durable rows → transition READY
→ FAIL: log issues, session stays RECOVERY_REQUIRED, no runtime state rebuilt from bad data
```

## Commits
`2c0b9af feat: implement real durable paper session recovery`,
`9c851ab test: verify durable persistence, idempotency and recovery on real PostgreSQL`

## Status change
F-04 recovery: **OPEN → RESOLVED_VERIFIED** (on PostgreSQL 16.2, disposable).

## Distinctions kept honest
- The prior `recover_session()` (journal-replay-only stub, always transitions to READY) is
  **unchanged** and still exists for the callers/tests that use it (round 1-3 compatibility).
  `recover_session_durable()` is the new, real, conditional recovery path.
- Fault-injection was demonstrated for **application-level** failures (mid-transaction
  exception, corrupted materialized row). True infrastructure-level fault injection (kill `-9`
  the actual FastAPI process mid-request) was not performed — the drill proves the recovery
  *logic* correctly detects and refuses to promote on bad data, using real Postgres round-trips,
  not that a literal process crash was survived.
- The live paper-trading runtime is not yet wired to call `recover_session_durable` from an API
  route; it exists and is verified as a service method, not yet triggered end-to-end from
  `apps/api/routers/paper.py`.
