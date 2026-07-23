# Alpha Research Campaign — Promotion Gate

## Purpose

This document defines the **only** criteria under which a strategy configuration produced by
`packages/research/campaign.py` may be written into published evidence
(`docs/research/ALPHA_RESEARCH_CAMPAIGN_EVIDENCE.md`). It is written *before* looking at
campaign results and is not adjusted post-hoc to whatever the campaign happens to produce —
doing so would defeat the point of having a gate.

Everything the campaign runs — pass or fail — is recorded in the unfiltered experiment
ledger at `docs/research/experiments/EXPERIMENT_LEDGER.csv`. Only rows that clear this gate
are ever summarized as "evidence."

## Why a gate at all

The platform's own architecture (ADR-001 in `docs/DECISIONS.md`) already treats agent output
as untrusted, uncalibrated, and subject to hard deterministic risk limits (0.25% risk/trade,
1.5% daily loss limit, 8% hard drawdown kill-switch) before anything reaches an order. The
research gate applies the same skepticism one layer up: a strategy *configuration* is not
"working" just because one backtest run over one time window happened to make money. With 15
configurations tested, some will look good on a single window by chance alone. The gate exists
to filter that out.

## Data and methodology

- **Source**: real Binance daily OHLCV candles for `BTC/USDT` and `ETH/USDT`, fetched from
  Binance's public data mirror (`data-api.binance.vision`) — see `packages/research/
  data_fetcher.py`. No synthetic or fabricated bars.
- **Range**: ~2019-01 through the campaign run date (~7.5 years), the full history available
  from the mirror.
- **Engine**: the real production `EventDrivenBacktestEngine` / `DecisionService` — the same
  code path used by paper trading. No shortcut or mocked signal generation.
- **Walk-forward folds**: the dataset is split into 3 sequential, non-overlapping blocks via
  `packages/backtest/walk_forward.py` (60% train / 20% validation / 20% test per block, with a
  7-day purge and 7-day embargo on each side of the test segment to reduce leakage at the
  boundary).
- **Out-of-sample definition**: because the platform's agents are fixed heuristics (no
  parameter fitting against train/validation data — see `packages/agents/strategy_config.py`),
  "out-of-sample" here means each fold's **test segment only**. The engine is given enough
  pre-test history to warm up its bounded feature-lookback window (see
  `FEATURE_LOOKBACK_WINDOW` in `packages/backtest/engine.py`) but is never allowed to open a
  position before the test segment begins.
- **In-sample / full-period runs** are also recorded in the ledger (`run_type=FULL_PERIOD`)
  for transparency, but are explicitly **excluded from gating** — they are the same window the
  configuration's parameters were eyeballed against when the grid was designed, so a good
  full-period number proves nothing on its own.

## Promotion gate criteria (`packages/research/gate.py: PromotionGate`)

A `(symbol, config)` pair passes the gate only if **all** of the following hold, computed
purely from its 3 out-of-sample test-fold results:

| # | Criterion | Threshold | Rationale |
|---|---|---|---|
| 1 | Every fold produced at least 1 trade | required | A fold with zero trades contributes no evidence either way; treated as insufficient sample rather than a free pass. |
| 2 | Total out-of-sample trades (summed across 3 folds) | ≥ 20 | Floor for statistical relevance — single-digit trade counts are not distinguishable from noise. |
| 3 | Profitable-fold ratio | ≥ 2 of 3 folds net-positive | A config that only worked in one out of three multi-month periods is regime-dependent luck, not an edge. |
| 4 | Mean out-of-sample Sharpe ratio (average of each fold's own annualized Sharpe, 0% risk-free rate) | ≥ 0.5 | Conservative bar for a daily-bar crypto long-only strategy; screens out paths that are merely "less bad than buy-and-hold noise." |
| 5 | Worst-fold max drawdown | ≤ 25% | Order-of-magnitude consistent with the platform's 8% hard kill-switch plus margin for backtest-vs-live slippage differences; a config that can draw down further than this in any one fold is not an evidence candidate regardless of its average return. |
| 6 | Aggregate net PnL across all 3 folds | > 0 | Sanity check on top of the ratio/Sharpe criteria. |

A **promoted** configuration additionally must pass the gate independently on **both**
BTC/USDT and ETH/USDT — a config that only works on one asset is asset-specific curve-fitting,
not a generalizable edge.

## What passing the gate does *not* mean

- It does not mean the strategy is approved for paper or live trading — that is a separate,
  explicit decision gated by the platform's existing Milestone/ADR process
  (`docs/CURRENT_STATE.md`, `docs/DECISIONS.md`), independent of this research campaign.
  `LIVE_TRADING_ENABLED` remains `false` regardless of any campaign outcome.
- It does not account for exchange-specific liquidity beyond the backtest engine's built-in
  slippage/fee model (10 bps taker fee, 5-10 bps slippage), funding costs, or execution
  capacity at size.
- Multiple-testing risk is reduced by the controlled (non-factorial) grid and the cross-asset
  requirement, but is not eliminated. A promoted config should still be treated as a
  hypothesis worth further, independent validation — not a proven edge.
