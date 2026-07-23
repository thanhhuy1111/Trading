# SESSION ISOLATION EVIDENCE (F-03)

| Finding | Implementation | Unit evidence | Integration evidence | Runtime evidence | Status |
|---|---|---|---|---|---|
| F-03 | Per-session injected `PortfolioLedger`; `ExitProtector` / `exit_governor` accept a session-scoped manager | `tests/unit/test_session_isolation_inmemory.py` (3 tests) | NONE (no DB) | In-memory only | **PARTIAL** (in-memory isolation verified; durable per-session persistence OPEN) |

## Verified (in-memory)
- `PositionManager` accepts an injected `PortfolioLedger`; two managers seeded 10,000 / 5,000 keep independent cash, positions, and NAV; a fill on A does not touch B.
- `PaperPipeline.get_position_manager` gives each session its own ledger seeded from the session's initial cash (`10,000` vs `5,000` verified distinct).
- `ExitProtector.evaluate_position_exit(..., owner_position_manager=pm)` writes trailing-stop state to the session manager; the global singleton is NOT mutated (`"ISO/TEST" not in position_manager.positions`).
- `exit_governor.validate_exit_intent(..., owner_position_manager=pm)` validates against the session manager (fixes the backtest exit that previously failed against the empty global manager).

## Design (back-compat preserved)
- Default `PositionManager()` (no ledger) still uses the module-global `portfolio_ledger` singleton, so backtest-legacy and existing tests are unchanged.
- Paper (and now backtest exits) inject session-scoped state → isolation.

## NOT verified here (honest)
- The global `portfolio_ledger` singleton still exists for legacy/default callers (routers, reconciliation). True per-session **durable** isolation (each session's ledger persisted to its own rows in Postgres) is part of F-04 and is BLOCKED (no Postgres).
- Cross-process isolation (two OS processes / workers) is not demonstrated.
