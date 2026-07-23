# FINDINGS REGISTER

Severity: CRITICAL · HIGH · MEDIUM · LOW · INFO
No **LIVE TRADING BOUNDARY VIOLATION** and no **lookahead** criticals were found. The CRITICAL below is a system-integrity finding, not a safety-boundary one.

---
## F-01 — CRITICAL (System Integrity): Multi-agent intelligence layer is dead code at runtime
- **Category:** architecture / misrepresentation
- **Files:** `packages/agents/runner.py`, `packages/governance/pipeline.py`, `packages/features/pipeline.py`; runnable paths `packages/paper/pipeline.py:109-133`, `packages/backtest/engine.py:168-197`
- **Evidence:** `grep` for callers of `run_agents`/`process_signals`/`AgentRunner`/`GovernancePipeline` in `packages/`+`apps/` → zero production callers (tests only). Paper & backtest fabricate `TradeIntent`s with hardcoded `confidence=0.85`, `net_edge_bps=120`.
- **Impact:** The documented Regime/Trend/Reversion/Breakout/Critic/Consensus/Allocator decision-making never runs. Executed logic is trivial and unrelated to the "multi-agent" claim.
- **Reproduction:** Trace callers; run paper/backtest and observe no agent/critic/consensus records produced.
- **Fix:** Wire `AgentRunner`+`GovernancePipeline` into the paper & backtest loops so real signals drive intents; delete fabricated intents.
- **Acceptance:** Paper/backtest runs persist agent_signals, critic_decisions, consensus_results, allocation_decisions tied to each executed trade.

## F-02 — HIGH: Paper trading has no market-data ingestion loop
- **Files:** `packages/paper/market_runtime.py`, `packages/paper/pipeline.py::process_candle_close`, `apps/api/routers/paper.py:101`
- **Evidence:** `process_candle_close`/`process_public_candle` only called from `tests/`. `start_runtime()` sets a boolean; nothing subscribes the Binance public WS to the pipeline.
- **Impact:** Cannot run 30-day continuous paper trading; the session "runs" but processes no candles.
- **Fix:** Add a worker that streams closed candles → `process_candle_close`.
- **Acceptance:** A started session ingests live closed candles and produces trades without manual test calls.

## F-03 — HIGH: No session isolation — global singleton ledger/position manager
- **Files:** `packages/positions/ledger.py:208` (`portfolio_ledger`), `packages/positions/manager.py:40,157,232` (`position_manager`), `packages/positions/exit_protector.py:7,51`
- **Evidence:** `PositionManager.process_fill` and `get_portfolio_snapshot` use the **module-global** `portfolio_ledger`; every session's fills mutate one shared cash balance. `ExitProtector` writes to global `position_manager`.
- **Impact:** Multiple paper/backtest sessions corrupt each other's cash/NAV; NAV = global cash + this-session asset value is wrong with >1 session. Breaks cash/position isolation invariants.
- **Fix:** Instantiate a per-session ledger owned by each `PositionManager`; inject the session manager into `ExitProtector`.
- **Acceptance:** Two concurrent sessions show independent cash/NAV; property test enforces isolation.

## F-04 — HIGH: Restart recovery is a no-op stub; state is in-memory only
- **Files:** `packages/paper/recovery.py:12-49`; state in `ledger.py`, `manager.py`, `paper/adapter.py` (all in-memory)
- **Evidence:** `recover_session` fetches journal entries, logs "Replaying …", then transitions to READY — it rebuilds **no** position/ledger/order state. Idempotency maps (`processed_fill_ids`, `submitted_orders`) are in-memory.
- **Impact:** After restart all positions/cash/fills are lost; because idempotency is in-memory, re-processing a persisted fill would **not** dedupe → duplicate-fill risk. Fails "restart without state loss / no duplicate fills."
- **Fix:** Persist fills/positions/ledger to DB; rebuild state by replaying the durable journal on recovery; make idempotency DB-backed.
- **Acceptance:** Kill+restart mid-session reproduces identical NAV/positions; replaying the same fill is a no-op.

## F-05 — HIGH: Daily/weekly loss limits never reset (lifetime-cumulative)
- **Files:** `packages/positions/manager.py:24-25,43-44`, consumed in `risk/state_machine.py:26-41`
- **Evidence:** `total_realized_pnl_today` / `_week` are incremented on every sell and **never reset** by day/week boundary.
- **Impact:** The daily-loss and weekly-loss kill switches evaluate lifetime realized PnL, not a rolling window → limits misfire or fail to fire; a core risk control is ineffective.
- **Fix:** Track realized PnL in time-bucketed windows with scheduled reset (UTC day/ISO week).
- **Acceptance:** Test proves daily loss resets at UTC midnight and triggers at the intended threshold.

## F-06 — HIGH: Documented ExecutionEngine + validation gate bypassed by paper & backtest
- **Files:** `packages/execution/engine.py`, `packages/execution/validator_gate.py`; bypassed in `paper/pipeline.py:99,160`, `backtest/engine.py:124,217`
- **Evidence:** Paper calls `PaperExchangeAdapter.submit_order` directly; backtest constructs `Fill` objects directly. Neither routes through `execution_validation_gate` (which enforces `maximum_entry_price`, expiry, mode).
- **Impact:** Order safety checks (max entry price, expiry, mode) are skipped in the runnable flows (see F-09). "Idempotent execution engine" tier is not in the executed path.
- **Fix:** Route all executions through `ExecutionEngine.execute_approved_order`.
- **Acceptance:** Paper/backtest fills carry validation-gate results; violating orders are BLOCKED.

## F-07 — HIGH (Strategy): Strategy quality not proven; no performance evidence, no baselines
- **Files:** agents & allocator (`reference_price=65000` hardcoded; `expected_return_bps=None`→const 50/150), `governance/cost_estimator.py` (const costs); runnable logic in `backtest/engine.py:171`, `paper/pipeline.py`
- **Evidence:** No backtest/paper performance artifacts in repo; executed logic is buy-on-1%-momentum (backtest) / buy-every-flat-candle (paper) with fabricated edge. No Buy&Hold/ablation comparison data.
- **Impact:** No basis to claim profitability or that multi-agent adds value.
- **Conclusion:** **STRATEGY QUALITY NOT PROVEN.**
- **Fix:** Run walk-forward backtests on registered datasets; produce metrics (net PnL, Sharpe/Sortino/Calmar, max DD, profit factor, expectancy) with baselines/ablations.
- **Acceptance:** Reproducible reports with DSR/PBO and baseline comparison committed under `docs/`.

## F-08 — MEDIUM: Simulator slippage nullified by min/max clamps
- **Files:** `packages/execution/simulator_adapter.py:93-99`
- **Evidence:** SELL `fill_price=max(best_bid*(1-slip), limit_price)`; BUY `fill_price=min(best_ask*(1+slip), limit_price, max_entry)`. `best_ask`/`best_bid` default to `limit_price` (fields absent on request), so slippage is clamped away and fills land exactly at limit.
- **Impact:** Simulator underestimates execution cost; PnL optimistic.
- **Fix:** Feed real best bid/ask; model slippage against reference mid, not the limit.
- **Acceptance:** Test shows non-zero slippage on both sides.

## F-09 — MEDIUM: Paper adapter fills ABOVE maximum_entry_price
- **Files:** `packages/paper/adapter.py:57-58`
- **Evidence:** BUY `fill_price = limit_price × 1.0005`; `limit_price = approved.maximum_entry_price` → fill exceeds the risk governor's hard entry cap by 5 bps. No cap enforced (gate bypassed, F-06).
- **Impact:** Violates the governor's `maximum_entry_price` guarantee; entry can exceed approved risk price.
- **Fix:** Clamp fill to `maximum_entry_price`; route through validation gate.
- **Acceptance:** Test: paper BUY fill ≤ maximum_entry_price always.

## F-10 — MEDIUM: Dashboard shows mock data & simulated "live" prices as real
- **Files:** `apps/dashboard/src/App.tsx:91-121` (mock positions/fills/orders), `:143` (`Math.random()` prices labeled "Binance feed")
- **Evidence:** Positions/fills/orders are hardcoded arrays; live prices generated client-side; only status/portfolio/configs/symbols fetched from API. Tabs `agents/orders/risk/backtest` self-labeled `isReal:false`.
- **Impact:** **INSUFFICIENT DECISION EXPLAINABILITY** — a user cannot determine from real data why the system bought BTC at a specific time; UI misrepresents live state and order types (STOP_LIMIT/partial fills) the backend does not produce.
- **Fix:** Bind trade/fill/signal/critic/risk tables to real per-trade backend data; remove random price generator.
- **Acceptance:** Dashboard renders the full real chain (signal→critic→consensus→intent→risk→order→fill) for a selected executed trade.

## F-11 — MEDIUM: Backtest exit realism (close-only stops, same-bar exit fill) & silent no-entry path
- **Files:** `packages/backtest/engine.py:112-139,210`
- **Evidence:** Exit triggers evaluated on `close_price` only (no intrabar high/low), exit fills same-bar at `close×0.999`; entry only fills when `same_bar_fill_allowed is False` (no `else` branch → if True, no entries at all).
- **Impact:** Optimistic exits (no gap-through-stop), and a config value silently disables entries.
- **Fix:** Evaluate stops against candle high/low; model exit fill on next bar or with gap logic; handle both same-bar settings.
- **Acceptance:** Stop-through-gap test; both `same_bar_fill_allowed` values produce defined behavior.

## F-12 — MEDIUM (Security): No authentication/authorization on any API route
- **Files:** all `apps/api/routers/*` (e.g., `trading.py`), `apps/api/main.py:64-70` (CORS `allow_origins=["*"]` + `allow_credentials=True`)
- **Evidence:** No auth dependency anywhere; `/trading/hard-stop`, `/paper/*`, config mutation endpoints are unauthenticated. `AUTHENTICATION_AND_AUTHORIZATION.md` documents controls that are absent in code.
- **Impact:** Anyone with network access can start/stop trading, trigger kill switch, mutate config. Doc–impl mismatch. (Wildcard CORS + credentials is itself invalid/unsafe.)
- **Fix:** Add authn/authz (even a token) before continuous operation; restrict CORS origins.
- **Acceptance:** Control/mutation endpoints require auth; CORS limited to the dashboard origin.

## F-13 — LOW: RiskGovernor crashes if called without `current_time`
- **Files:** `packages/risk/governor.py:39,49,...` use `current_time` (default `None`) directly instead of `eval_time`.
- **Evidence:** `intent.expires_at <= current_time` with `current_time=None` → TypeError.
- **Impact:** Robustness only (all current callers pass `current_time`).
- **Fix:** Use `eval_time` consistently.

## F-14 — LOW: RSI uses simple average, not Wilder smoothing
- **Files:** `packages/features/calculators/momentum.py:47-48` — accuracy deviation (not lookahead).

## F-15 — INFO
- No LLM/AI dependency or call anywhere (status **A** — see LLM section of main report).
- Git repo has **zero commits**; entire tree uncommitted.
- Live-trading boundary enforced at 5 layers (config defaults, startup kill switch `main.py:39-42`, `RiskPolicyConfig` validator, `DisabledLiveExchangeAdapter`, allocator SHORT block; public-only Binance adapter). `disabled_live_adapter` is defensive but never wired to a factory.
- `mypy`/`alembic` not installed; `docker` not installed → those gates not executed.
