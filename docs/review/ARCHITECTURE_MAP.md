# ARCHITECTURE MAP — Documented vs. Actual (Code-Verified)

## Documented pipeline (README / plan.md)
```
Market Data → Feature Engine → Alpha & Context Agents (Regime, Trend, Reversion, Breakout)
→ Critic → Meta Allocator (Net Edge & TradeIntent) → Risk Governor → Execution Engine
→ Paper Exchange → Position Manager → Ledger → Dashboard / Audit / Observability
```

## Actual runtime reality (verified by call-graph tracing)

There are **three disconnected islands** of code:

### Island 1 — "Multi-agent intelligence" (EXISTS, but DEAD at runtime)
`packages/features/*` → `packages/agents/runner.py::AgentRunner.run_agents` → `packages/governance/pipeline.py::GovernancePipeline.process_signals` (critic → consensus → allocator → TradeIntent).

**Wiring status:** `grep` for callers of `run_agents`, `process_signals`, `AgentRunner`, `GovernancePipeline` across `packages/` and `apps/` returns **zero** production callers. Only unit tests instantiate them. → This entire documented chain never executes in any running pipeline, API route, worker, or scheduler.

### Island 2 — Backtest (RUNNABLE, but bypasses Island 1)
`apps/api/routers/backtests.py` → `packages/backtest/engine.py::EventDrivenBacktestEngine.run_backtest`.
- Strategy = **inline hardcoded rule** (`engine.py:169-171`): `if close > close[idx-5] * 1.01` → BUY.
- Fabricates `TradeIntent` with hardcoded `confidence=0.85`, `expected_return_bps=150`, `net_edge_bps=120` (`engine.py:173-197`).
- Calls real `deterministic_risk_governor.evaluate_intent` (good) → constructs `Fill` objects **directly** (skips ExecutionEngine + validation gate) → `PositionManager.process_fill`.
- Entry fills at **next candle open** (`engine.py:210-232`) — no same-bar entry fill. Exit fills same-bar at close.

### Island 3 — Paper trading (RUNNABLE stub, bypasses Islands 1 & 2's logic)
`apps/api/routers/paper.py` → `packages/paper/pipeline.py::PaperPipeline.process_candle_close`.
- Strategy = **none**. On every candle close with no open position it fabricates a `TradeIntent` with hardcoded `market_regime=TREND_UP`, `confidence=0.85`, `net_edge_bps=120`, random signal IDs (`pipeline.py:109-133`).
- Calls real `deterministic_risk_governor` (good) → `PaperExchangeAdapter.submit_order` (skips ExecutionEngine + validation gate) → `PositionManager.process_fill`.
- **`process_candle_close` has no production caller** — only tests call it. `PaperMarketRuntime.process_public_candle` (the "stream") validates candles but **never invokes the pipeline**. `start_runtime()` only flips a boolean.

### Island 4 — ExecutionEngine (EXISTS, bypassed by Islands 2 & 3)
`packages/execution/engine.py::ExecutionEngine.execute_approved_order` (+ `validator_gate`, `planner`, `simulator_adapter`). Called only by `apps/api/routers/execution.py` (manual one-shot endpoint) and `packages/execution/pipeline.py`. Neither backtest nor paper routes it through here — they call adapters / build fills directly.

## Step-by-step actual map (what really runs in paper mode)

| Step | File / Symbol | Input | Output | Failure behavior | Idempotency |
|---|---|---|---|---|---|
| Market data (public) | `market_data/adapters/binance.py` (klines/depth REST, public WS) | symbol/timeframe | `Candle` | urllib timeout 10s | none |
| Stream runtime | `paper/market_runtime.py::process_public_candle` | Candle+seq | bool healthy; **does not feed pipeline** | clock-skew>5s→DEGRADED; seq gap→log | seq tracking (in-mem) |
| Candle processing | `paper/pipeline.py::process_candle_close` (**test-only caller**) | Candle | fills via adapter | dedup by `(session,symbol,tf,close_time)` in-mem | in-mem dict |
| Data Guardian | `market_data/guardian.py::validate_ohlc` | OHLC | bool | invalid OHLC → skip candle (fail-closed) | n/a |
| "Strategy" | `paper/pipeline.py:109` | — | hardcoded BUY TradeIntent | n/a | n/a |
| Risk Governor | `risk/governor.py::evaluate_intent` | intent+snapshot | RiskDecision + ApprovedOrder | reject/soft/hard stop | fingerprint (advisory) |
| Sizing | `risk/calculator.py` | budget, stop | qty (Decimal, ROUND_DOWN) | invalid → reject | n/a |
| Fill | `paper/adapter.py::submit_order` | ExchangeOrderRequest | Fill (full, taker) | — | client_order_id in-mem |
| Ledger | `positions/ledger.py` (**global singleton**) | Fill | LedgerEntry, RealizedPnl | negative cash/asset → raise | fill_id in-mem |
| Position | `positions/manager.py` (per-session + calls global ledger) | Fill | Position, snapshot | insufficient qty → raise | via ledger |
| Exit monitor | `positions/exit_protector.py` | Position, price | SELL exit intent | close-only trigger | writes to **global** pos mgr (bug) |
| Dashboard | `apps/dashboard/src/App.tsx` | REST polling | UI | mock fallback | n/a |

## Transaction boundaries
- Governance/agent DB writes use `outbox` in same `AsyncSession` (good pattern) — but that path is dead code.
- Paper/backtest keep **all state in-memory** (module-level singletons `portfolio_ledger`, `position_manager`; per-session dicts in pipelines). No DB persistence of fills/positions in the runnable flows; no transactional durability.

## Classification of key documented claims
| Claim | Status |
|---|---|
| 3-tier: Agents→Risk→Execution | **DOCUMENTATION–IMPLEMENTATION MISMATCH** (agents & execution engine bypassed at runtime) |
| Multi-agent debate (critic/consensus/allocator) | IMPLEMENTED BUT NOT WIRED (dead code) |
| Feature engine zero-lookahead | VERIFIED IN CODE (but unused by runnable flows) |
| Risk Governor deterministic veto | VERIFIED IN CODE |
| Live trading disabled at multiple layers | VERIFIED IN CODE |
| Paper trades via same pipeline as backtest | **MISMATCH** (different fabricated logic in each) |
| Backtest vs paper comparison | MISLEADING (neither uses the agents; logic differs) |
| Restart recovery without duplicate fills | **MISMATCH** (recovery is a no-op stub; state is in-memory) |
| Real-time Binance feed in dashboard | **MISMATCH** (Math.random simulated prices; mock tables) |
| No LLM in trading decisions | VERIFIED (no LLM anywhere) |
