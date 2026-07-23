# PRIORITIZED REMEDIATION PLAN

Goal: reach **controlled, continuous 30-day paper trading** with trustworthy accounting and a decision trail. Ordered by dependency, not just severity.

## Phase 0 — Make the real pipeline actually run (blocks everything)
1. **Wire the intelligence layer (F-01).** In paper & backtest loops: compute features (`feature_pipeline`) → `AgentRunner.run_agents` → `GovernancePipeline.process_signals` → use the resulting real `TradeIntent`. Delete the fabricated intents in `paper/pipeline.py:109-133` and `backtest/engine.py:173-197`.
2. **Add a market-data ingestion worker (F-02).** Subscribe the Binance public WS/klines to `process_candle_close` on closed-candle boundaries; connect `PaperMarketRuntime` to the pipeline.
3. **Route executions through `ExecutionEngine` + validation gate (F-06, F-09).** Remove direct adapter/`Fill` construction; enforce `maximum_entry_price`.

## Phase 1 — Correct, isolated, durable accounting
4. **Per-session ledger & position manager (F-03).** Own a ledger instance per `PositionManager`; inject session manager into `ExitProtector`. Remove module-global singletons from the hot path.
5. **Persist state + real recovery (F-04).** Write fills/positions/ledger to Postgres in a transaction; rebuild state by replaying the durable journal; make idempotency DB-backed (unique on `fill_id`/`client_order_id`).
6. **Time-windowed loss tracking (F-05).** Bucket realized PnL by UTC day / ISO week with scheduled reset; verify daily/weekly kill switches.

## Phase 2 — Execution realism
7. **Real fill model (F-08, F-09, F-11).** Feed best bid/ask; slippage vs. mid; clamp to caps; evaluate stops against candle high/low; define both `same_bar_fill_allowed` behaviors.

## Phase 3 — Prove the strategy
8. **Walk-forward backtests + baselines (F-07).** Run on registered datasets; emit net PnL, Sharpe/Sortino/Calmar, max DD, profit factor, expectancy, turnover; compare Buy&Hold and per-agent ablations; report DSR/PBO. Only then judge whether multi-agent adds value.

## Phase 4 — Observability & security for continuous ops
9. **Real dashboard (F-10).** Bind trade/fill/signal/critic/risk tables to backend; remove `Math.random` prices; render the full per-trade decision chain.
10. **API auth + CORS (F-12).** Add authn/authz on control/mutation endpoints; restrict CORS origin.
11. **Robustness (F-13, F-14).** Fix `eval_time` usage; Wilder RSI.

## Environment/process gaps to close before sign-off
- Install dev extras (run `mypy`, `alembic upgrade/downgrade` on a disposable DB, `hypothesis`).
- Run integration tests against ephemeral Postgres/Redis.
- Run `docker compose config`/`build` on a host with Docker.
- Commit the repository (currently **zero commits**) and enable CI to run ruff/pytest/build/mypy on every change.

## Suggested acceptance gate for "30-day paper" readiness
- Real agent→governance→risk→execution chain runs on live public candles unattended for the full window.
- Independent PnL reconciliation: `NAV == cash + Σ market_value` holds continuously; fees counted once; no negative cash/position.
- Restart drills reproduce identical state with no duplicate fills.
- Daily/weekly loss + drawdown kill switches drilled and verified.
- Dashboard explains every executed trade from real data.
- No unhandled incidents; slippage model within tolerance of observed.
