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

## What is NOT yet runtime-proven
- This chain is driven programmatically / by tests. There is still **no live market-data worker** feeding `process_candle_close` (F-02), so continuous unattended operation is not demonstrated.
- Backtest still uses its inline momentum rule, not this chain (F-01 backtest OPEN).
- State is in-memory; restart durability and true session isolation are not proven (F-03/F-04).
