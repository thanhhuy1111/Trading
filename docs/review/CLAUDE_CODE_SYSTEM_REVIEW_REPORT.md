# CLAUDE CODE — INDEPENDENT SYSTEM REVIEW REPORT
### Crypto Multi-Agent Trading System
**Date:** 2026-07-23 · **Mode:** REVIEW ONLY · **Reviewer:** Claude Code (Architect / Quant / AppSec / SRE / Ledger)

Companion files: [ARCHITECTURE_MAP](ARCHITECTURE_MAP.md) · [AGENT_LOGIC_MATRIX](AGENT_LOGIC_MATRIX.md) · [FINDINGS_REGISTER](FINDINGS_REGISTER.md) · [COMMAND_EVIDENCE](COMMAND_EVIDENCE.md) · [REMEDIATION_PLAN](REMEDIATION_PLAN.md) · [REVIEW_PLAN](REVIEW_PLAN.md)

---
## 1. Executive Summary
The repository is a well-organized, heavily-documented Python monorepo whose **individual components are clean, Decimal-safe, and unit-tested (109/109 unit tests pass, ruff clean, frontend builds).** The **safety boundary is strong**: no LLM anywhere, no private exchange API, public-only market data, and live trading blocked at five independent layers.

However, the system **does not work the way it is documented**. The advertised "multi-agent intelligence" (Regime/Trend/Reversion/Breakout → Critic → Consensus → Meta-Allocator) is fully implemented but **never invoked at runtime** — it is dead code exercised only by tests. The two runnable flows (backtest and paper) **fabricate trade intents with hardcoded confidence/edge** and bypass both the agent layer and the documented Execution Engine. Paper trading additionally has **no market-data ingestion loop**, **no session isolation** (global singleton ledger), **no real restart recovery**, and **ineffective daily/weekly loss limits**. The dashboard displays **mock data and `Math.random` "live" prices**.

Net: this is a strong **skeleton/scaffold with excellent guardrails**, but the intelligence, execution-integrity, operability, and observability required for continuous paper trading are **not yet connected**. **Strategy profitability is unproven.**

**Final decision: C — NOT READY FOR PAPER TRADING** (for the 30-day continuous goal).

---
## 2. Actual Architecture
See [ARCHITECTURE_MAP](ARCHITECTURE_MAP.md). Reality is **four disconnected islands**: (1) multi-agent chain — dead code; (2) backtest — inline momentum rule; (3) paper — buy-every-flat-candle stub with no stream wired; (4) ExecutionEngine — bypassed by (2)/(3). Only the **Risk Governor** and **Feature Engine** are both correct *and* reused; the governor is the one tier that is genuinely in every executed path.

## 3. Repository Map
`packages/` (~12.4k LOC): agents, features, governance, risk, execution, positions, paper, backtest, market_data, events, outbox/inbox, audit, telemetry, config_manager, schemas, common. `apps/api` (24 routers) + `apps/dashboard` (single 1572-line `App.tsx`). `infra/migrations` (12 Alembic revisions). `tests/unit` (34 modules) + `tests/integration` (7, DB-dependent). Git: **0 commits**.

## 4. Agent Logic Review
See [AGENT_LOGIC_MATRIX](AGENT_LOGIC_MATRIX.md). All agents are **deterministic, rule-based**, thresholds hardcoded, confidence a fixed heuristic constant, `expected_return_bps=None` (defaulted to 50 bps downstream), `reference_price=65000.00` hardcoded. No agent can size, order, reach the exchange, or bypass risk. SHORT is blocked (spot-only). **These agents do not run in production paths (F-01).**

## 5. LLM / API Detection — **Status A: NO LLM API DETECTED**
Exhaustive scan (source, tests, `pyproject.toml`, `package.json`, docker-compose, `.env`) for all major providers and SDK call signatures → **zero hits**. There are no API keys, prompts, HTTP LLM clients, or model configs. The agents are pure Python rules. **LLM influences no step and cannot bypass the Risk Governor** (there is no LLM).

## 6. Market Data Integrity
Public Binance adapter (klines/depth REST + public WS), no keys. `DataGuardian.validate_ohlc` enforces OHLC sanity and **fails closed** (invalid candle → skipped; no trade). `PaperMarketRuntime` checks clock-skew (>5s → DEGRADED) and sequence gaps. Limitations: guardian validates single-candle integrity + freshness only; duplicate/out-of-order/late detection is partial; **the runtime does not feed candles into the pipeline (F-02).**

## 7. Feature & Lookahead Review — **CLEAN**
`FeaturePipeline.compute` filters `c.is_closed and c.close_time <= as_of_time` and sorts; calculators use trailing windows only. `FeatureSnapshot` enforces `lookback_end <= as_of_time`. The **future-data invariance test passes** (`test_lookahead_leakage.py`). No `shift(-1)`, no whole-dataset normalization, no same-bar close usage. **No lookahead found.** (Caveat: features are consumed only by the dead-code agent path.)

## 8. Decision Pipeline
Critic invariant `0 ≤ adjusted ≤ original ≤ 1` enforced by schema validator; Consensus is confidence-weighted with conflict detection; Meta-Allocator emits `TradeIntent(BUY, PENDING_RISK_REVIEW)` with **no sizing fields** (validator-forbidden) and blocks SHORT. `net_edge = weighted_expected_return × weighted_confidence − cost` — but both terms are constants in practice, so "net edge" carries no predictive information. Units are consistent (bps/Decimal). **This pipeline is not wired into execution (F-01).**

## 9. Risk Governor Review — **STRONGEST COMPONENT**
Deterministic, Decimal throughout, independent of any LLM. Policy validator hard-forbids leverage/short/margin/live. In every executed path.

| Case | Expected | Actual (code) |
|---|---|---|
| Insufficient cash | Reject | ✅ sizing cap `quantity_by_cash` + ledger raises on negative cash |
| Excess symbol exposure | Reject/reduce | ✅ `quantity_by_symbol` cap |
| Excess portfolio exposure | Reject/reduce | ✅ `quantity_by_total` cap |
| Daily loss exceeded | Hard stop | ⚠️ logic present but PnL never resets (F-05) |
| Drawdown exceeded | Hard stop | ✅ `state_machine` hard-stop at `hard_stop_drawdown_pct` |
| Stale market data | Reject | ✅ intent freshness / snapshot age checks |
| Stale portfolio snapshot | Reject | ✅ `PORTFOLIO_SNAPSHOT_STALE` |
| Kill switch active | Reject | ✅ HARD_STOP short-circuits |
| Invalid price/stop | Reject | ✅ stop must be `< reference`; distance bounds |
| Invalid quantity | Reject | ✅ min qty/notional, round-down |
| Short intent | Reject | ✅ blocked at allocator (spot MVP) |
| Leverage intent | Reject | ✅ policy validator forbids |

All safety-critical math uses `Decimal`. No bypass path found (agents cannot reach execution; execution requires an `ApprovedOrder`). Minor robustness bug F-13.

## 10. Execution Review
Runnable paths call adapters directly and **skip the ExecutionEngine validation gate (F-06)**. Within a single process, idempotency holds (in-memory `client_order_id`/`fill_id` maps; duplicate submit returns cached). **Across restart, idempotency is lost (F-04)** → duplicate-fill risk + total state loss. Simulator **slippage is clamped away (F-08)**; paper adapter **fills above `maximum_entry_price` (F-09)**. Fills are always full (no partial-fill modeling in runnable paths). SELL/BUY accounting directions are correct.

## 11. Ledger & PnL Review
Accounting logic is correct **per fill**: BUY debits cash+fee, credits asset; SELL credits net proceeds, debits asset, realizes `proceeds − released_cost − fee`; fee counted once each side; average cost updated on adds; `NAV = cash + Σ market_value`; negative cash/asset raise. **But** the ledger is a **global singleton shared across sessions (F-03)**, so multi-session cash/NAV is wrong, and state is in-memory/non-durable (F-04). Fee is **not** double-counted; no obvious per-fill PnL error found. Reconciliation module exists but is not in the runtime loop.

## 12. Backtest Reliability
Event-driven replay with dataset checksum + config fingerprint; **no same-bar entry fill** (fills at next open); Data Guardian gate; warmup filter. Positives are real. Concerns: strategy is a trivial inline rule (not the agents), exits are **close-only and same-bar (F-11)**, slippage/fees are flat constants, and a `same_bar_fill_allowed=True` config silently disables entries. Reproducibility is plausible (metrics derive from deterministic prices; UUIDs differ but don't affect metrics) but was **not executed here** for a two-run diff. Future-invariance is enforced at the feature layer (passing test).

## 13. Strategy Quality — **NOT PROVEN**
No committed backtest/paper performance artifacts; executed logic is non-predictive (constant edge, hardcoded reference price); no Buy&Hold / no-trade / per-agent ablation data. Unit tests prove *mechanics*, not *profitability*. Multi-agent value is **undemonstrated** (the agents don't even run). **Conclusion: STRATEGY QUALITY NOT PROVEN.**

## 14. Paper Trading Readiness
Not ready: no ingestion loop (F-02), no session isolation (F-03), no real recovery (F-04), ineffective daily/weekly limits (F-05), gate-bypassing execution (F-06/F-09). Session state machine, journal, warmup, and comparison scaffolding exist but are not driven by a real continuous loop.

## 15. Dashboard & Explainability — **INSUFFICIENT**
Single React file with hardcoded positions/fills/orders and `Math.random` prices labeled as the Binance feed (F-10). Only status/portfolio/configs/symbols are fetched. A user **cannot** reconstruct why a specific BTC buy occurred from real data. Run via `cd apps/dashboard && npm run dev` (http://localhost:5173) against API on `:8000`. → **INSUFFICIENT DECISION EXPLAINABILITY.**

## 16. Security & Live Boundary — **BOUNDARY GOOD; API AUTH MISSING**
Live trading blocked at: config defaults, startup kill switch (`main.py:39-42`), `RiskPolicyConfig` validator, `DisabledLiveExchangeAdapter`, allocator SHORT block; Binance adapter is public-only; no secrets in source; audit redactor lists secret fields. **No LIVE TRADING BOUNDARY VIOLATION found.** Weaknesses: **no authentication/authorization on any API route** and wildcard CORS with credentials (F-12) — anyone on the network can trigger start/stop/kill-switch/config changes.

## 17. Findings
Full register in [FINDINGS_REGISTER](FINDINGS_REGISTER.md): **1 CRITICAL (integrity)**, **6 HIGH**, **5 MEDIUM**, **2 LOW**, plus INFO. No safety-boundary or lookahead criticals.

## 18. Command Evidence
See [COMMAND_EVIDENCE](COMMAND_EVIDENCE.md). ruff PASS; pytest unit 109/109 PASS; frontend build PASS. mypy/alembic/docker/integration not runnable in this environment (documented).

## 19. Prioritized Remediation Plan
See [REMEDIATION_PLAN](REMEDIATION_PLAN.md). Phase 0 (wire agents, add ingestion, route through execution engine) is the precondition for everything else.

## 20. Answers to the 20 Mandated Questions
1. **Model/Agent API?** None. No LLM/ML. Pure deterministic Python (status A).
2. **Agent type?** Rule-based.
3. **Features per agent?** Regime: adx/slope/vol; Trend: regime+ema_slope; Reversion: rsi/zscore(+regime); Breakout: donchian/relative_volume (see matrix).
4. **Where are thresholds?** Hardcoded in each agent source file (not config).
5. **Can an agent place orders?** No.
6. **Risk Governor bypass path?** None found.
7. **Lookahead?** None (feature engine verified clean).
8. **Invalid same-bar fill?** Entry no; backtest **exit** fills same-bar at close (F-11).
9. **Fee double-counted?** No — once per side.
10. **Cash/ledger/position/PnL consistent?** Per-fill yes; **cross-session no** (global ledger, F-03).
11. **Restart duplicate fills?** Yes — in-memory idempotency + no real recovery (F-04).
12. **Paper & backtest same pipeline?** No — different fabricated logic; neither uses the agents (F-01).
13. **Dashboard explains each trade?** No (F-10) — INSUFFICIENT.
14. **Private exchange API exists/called?** No — public-only.
15. **Live trading path exists?** No executable one; blocked at 5 layers.
16. **Strategy proven profitable?** No — NOT PROVEN.
17. **Multi-agent better than baseline?** Undemonstrated (agents don't run; no comparison data).
18. **Ready for 30-day paper?** No.
19. **Top 3 risks?** (a) Intelligence layer not wired (F-01); (b) no isolation + no durable state/recovery (F-03/F-04); (c) unproven strategy + ineffective daily-loss limit (F-07/F-05).
20. **Next 5 actions?** Wire agents→governance into paper/backtest; add market-data ingestion worker; per-session durable ledger + real recovery; time-windowed loss limits; run walk-forward backtests with baselines.

## 21. Final Decision & Confidence
**FINAL DECISION: C — NOT READY FOR PAPER TRADING.**
The system is not cleared for live trading and is not yet operable for continuous paper trading. Distinctions: Risk Governor & Feature Engine are *implemented, tested, and runtime-reachable*; the multi-agent layer is *implemented and tested but not runtime-reachable*; strategy profitability and 30-day operability are *neither tested nor operationally proven*.

**CONFIDENCE: HIGH** on architecture wiring, agent logic, LLM absence, lookahead, and live-boundary conclusions (derived from reading actual runtime code paths and passing tests). **MEDIUM** on operational/DB/reproducibility items not executed here (integration tests, alembic, docker, two-run backtest diff) due to environment limits noted in COMMAND_EVIDENCE.
