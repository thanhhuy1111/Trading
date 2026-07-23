# RUNTIME EVIDENCE — real end-to-end decision → execution chain

Captured by running `decision_service.decide(...)` on a 40-candle uptrend, then routing the
resulting intent through the deterministic Risk Governor, the paper adapter, and the ledger
(reproducible via the snippet in the review notes / `tests/unit/test_decision_pipeline_e2e.py`).

```
FeatureSnapshot: babb58a0-…-f025a075a00b | ema_20_slope=0.01507… adx_14=100
Regime: TREND_UP | strategy_config_hash: c63e557c0481f357…
  Signal trend_agent_v1     action=LONG      conf=0.75 exp_bps=375.0  -> Critic approved=True  adj_conf=0.75
  Signal reversion_agent_v1 action=NO_SIGNAL conf=0.50 exp_bps=None   -> Critic approved=False adj_conf=0.30
  Signal breakout_agent_v1  action=NO_SIGNAL conf=0.50 exp_bps=None   -> Critic approved=False adj_conf=0.30
Consensus: 76945d6f-…-4163ea2efb15  LONG  w_conf=0.75  w_ret_bps=375.0
Allocation: TRADE_INTENT_CREATED
TradeIntent: f4ee9041-…-2cbb2614cfd7  side=BUY  ref=61039.71  net_edge_bps=259.25  consensus_id_match=True
RiskDecision: APPROVED | ApprovedOrder qty=0.099  max_entry=61100.75
Fill: f229b157-…  price=61070.23  (<= max_entry: True)  fee=6.0459…
Position: BTC/USDT qty=0.099  avg=61131.30
Ledger cash: 93948.00  | NAV=99993.95
```

## What this proves
- The **real** multi-agent chain executes (features → regime agent → 3 alpha agents → critic → consensus → allocator). No fabricated intent.
- Reference price is the **live candle close (61039.71)** — the hardcoded `65000.00` is gone.
- Expected return (`375 bps`) is derived from the trend agent's own target × confidence, not the old constant `50/150`. Non-directional agents contribute `None` → treated as 0 (no fake edge).
- Critic **lowered** the rejected agents' confidence (0.50 → 0.30) and never raised any.
- Linked lineage: `TradeIntent.consensus_id == Consensus.consensus_id`; strategy config hash recorded.
- Risk Governor independently sized the order; the paper **fill price (61070.23) ≤ maximum_entry_price (61100.75)** — F-09 cap holds, with non-zero slippage (F-08).
- Ledger/position/NAV are internally consistent (`NAV = cash + qty × mark`).

## Round 2 additions (verified at unit level)
- **Backtest now runs this same chain** (F-01 backtest closed): `test_backtest_actually_trades_through_pipeline` replays a 60-candle rise-then-fall dataset — DecisionService produces a LONG, the Risk Governor sizes it, a next-open capped fill opens the position, and the session-scoped exit governor closes it on the drop → `report.trade_count >= 1`, `status == COMPLETED`.
- **Ingestion worker** drives `process_candle_close` from a fake stream with closed-candle-only / dedup / out-of-order / gap→DEGRADED→backfill→RUNNING / clock-skew / clean-cancel semantics, and blocks new entries while DEGRADED (`test_paper_ingestion_worker`).
- **Session isolation (in-memory):** two sessions keep independent cash/positions/NAV; exit paths write to the session manager, not the global singleton (`test_session_isolation_inmemory`).
- **Risk windows:** realized PnL is bucketed by UTC day / ISO week from fill event time (`test_risk_pnl_windows`).

## Round 3 note (durable persistence)
The durable persistence layer (schema/migration 013, atomic fill-commit orchestration, DB
idempotency, recovery reconciliation) was implemented and verified at the DESIGN/LOGIC level only
(DDL compiles for postgres; offline `alembic --sql`; orchestration + reconciliation unit tests).
It was **NOT executed against PostgreSQL** (no server) and is **not yet wired as the runtime
source of truth** — the live paper pipeline still uses in-memory state. See
DATABASE_TRANSACTION_EVIDENCE.md, DB_IDEMPOTENCY_EVIDENCE.md, RECOVERY_DRILL_EVIDENCE.md.

## Round 4 (REAL PostgreSQL 16.2, disposable container)
Docker Desktop installed; a disposable PostgreSQL 16.2 container was used (isolated from an
unrelated pre-existing process bound to the host's `:5432`, never touched). Running the
migration chain for the FIRST TIME EVER against a real database surfaced and fixed a systemic,
pre-existing defect (7 duplicate table declarations across 001/003/005/006/007/008 — see
MIGRATION_EVIDENCE.md). After the fix:
- `alembic upgrade head` / `downgrade -1` / `upgrade head`: **PASS** (111 tables).
- 12/12 integration tests pass for real: atomic fill-commit + rollback, fill/order/candle
  DB-backed idempotency (including genuine `asyncio.gather` concurrent races), durable session
  isolation, restart-drill reconciliation (both the pass path and the fail-safe
  `RECOVERY_REQUIRED` path), durable PnL buckets surviving restart, late-fill correct bucketing.
- `docker compose build` succeeds for both `trading-api` and `trading-dashboard` images.

This is genuine, first-time, real-database evidence for F-02/F-03/F-04/F-05's persistence
mechanism — see DATABASE_TRANSACTION_EVIDENCE.md, DB_IDEMPOTENCY_EVIDENCE.md,
SESSION_ISOLATION_EVIDENCE.md, RECOVERY_DRILL_EVIDENCE.md, RISK_WINDOW_EVIDENCE.md for the
per-test breakdown.

## What is NOT yet runtime-proven
- The live `PaperPipeline`/`PaperIngestionWorker` runtime loop does not yet call this
  now-verified durable mechanism — it still operates in-memory only (wiring is the next item).
- No **live** market-data feed; the worker was verified only with a fake in-process stream (F-02 PARTIAL, live feed).
- No burn-in / continuous-operation drill has been run. `mypy` was not run this round.
