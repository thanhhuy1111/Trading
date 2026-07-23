# REMAINING LIMITATIONS (nothing hidden)

This pass delivered a real, verified paper decision pipeline plus several safety fixes, but
the system is **NOT** yet ready for continuous paper trading. The following are open.

## Not implemented (findings still OPEN)
- **F-02 — no market-data ingestion worker.** `process_candle_close` is still driven by tests/callers, not a live Binance public-WS/REST worker. `start_runtime()` still only flips a flag. Continuous unattended operation is not possible. *(Blocked here: no network/async-worker runtime to verify against.)*
- **F-04 — no durable persistence / real recovery.** All paper state (ledger, positions, orders, idempotency maps) is in-memory. `recover_session` is still a stub. Restart loses state and could reprocess fills (duplicate risk). *(Blocked here: no Postgres.)*
- **F-03 — session isolation only partially fixed.** `ExitProtector` no longer forces the global manager, but `portfolio_ledger` is still a module-global singleton shared across sessions. True per-session ledgers require the F-04 persistence work.
- **F-05 — daily/weekly loss limits still lifetime-cumulative.** `PositionManager.total_realized_pnl_today/_week` never reset by UTC day / ISO week; the daily-loss kill switch is still unreliable. *(Deferred to avoid destabilizing risk/accounting tests without the time-bucketing + clock injection done carefully.)*
- **F-06 — execution not fully routed through `ExecutionEngine`.** Paper entries now pass the `execution_validation_gate`, but do not go through `ExecutionEngine.execute_approved_order`; backtest still builds fills directly.
- **F-01 (backtest) — backtest not rewired.** Backtest still uses its inline `close>close[idx-5]*1.01` rule and fabricated confidence/edge. Rewiring it to `decision_service` entangles with checkpoint/resume semantics (`test_checkpoint_resume` assumes a flat boundary), which needs the F-04 persistence/checkpoint work first.
- **F-07 — strategy unproven.** The new expected-return value is a transparent proxy (target distance × confidence), NOT a calibrated forecast. No out-of-sample / walk-forward / baseline (Buy&Hold, ablation) evidence exists. Do not interpret any positive edge as profitability.
- **F-10 — dashboard still uses mock data / `Math.random` prices.** Unchanged.
- **F-11 — backtest exit realism unchanged.** Close-only stops, same-bar exit fill.
- **F-12 — API routes still unauthenticated.** An RBAC library exists (`packages/governance/security.py`) but is not enforced on FastAPI routes; CORS is still `["*"]` with credentials.

## Quality gates not executed here
- `mypy` (typecheck), `alembic` (migration cycle), `docker compose config/build`, and `tests/integration` (Postgres/Redis) were NOT run — tools/infra unavailable. These must pass on a proper environment before any readiness upgrade.
- Ran under Python 3.10; the project targets 3.12. Re-run all gates on 3.12.
- No endurance / burn-in test has been run (30-day continuous paper is not demonstrated).

## Safety posture (unchanged, still enforced)
`LIVE_TRADING_ENABLED=false`, `PRIVATE_EXCHANGE_API_ENABLED=false`, `FEATURE_FLAGS_LIVE_TRADING=false`.
No private exchange API, no order-placement to a real exchange, no credentials, no LLM in the
decision path were added. All exchange interaction remains public-market-data + paper simulator.
