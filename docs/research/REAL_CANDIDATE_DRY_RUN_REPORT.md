# Real Candidate Dry Run Report

_Real, no-ML dry run of validate -> feature -> regime -> route -> decide -> candidate across every real 1h/4h dataset fetched in Checkpoint 2 (BTC/ETH/BNB/SOL). No fills, no PnL, no training — this exercises the wiring at real scale and counts what happened. See methodology note in `packages/research/candidate_dry_run.py` for how `dropped_by_stale_policy` is adapted from a live-runtime concept to historical replay._

| Symbol | TF | Clean Candles | Valid Pts | Dropped(Gap) | Dropped(Stale) | Routed Agent Execs | Candidates | Completed Labels | Duplicates | Lineage Viol. | Leakage Viol. | Time(s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 1h | 35758 | 35480 | 250 | 25 | 35480 | 9327 | 9324 | 0 | 0 | 0 | 75.39 |
| ETH/USDT | 1h | 35758 | 35480 | 250 | 25 | 35480 | 9942 | 9940 | 0 | 0 | 0 | 80.55 |
| BNB/USDT | 1h | 35758 | 35480 | 250 | 25 | 35480 | 9262 | 9261 | 0 | 0 | 0 | 84.73 |
| SOL/USDT | 1h | 35758 | 35480 | 250 | 25 | 35480 | 10451 | 10450 | 0 | 0 | 0 | 79.96 |
| BTC/USDT | 4h | 11129 | 11101 | 0 | 0 | 11101 | 3399 | 3395 | 0 | 0 | 0 | 26.14 |
| ETH/USDT | 4h | 11129 | 11101 | 0 | 0 | 11101 | 3451 | 3439 | 0 | 0 | 0 | 26.35 |
| BNB/USDT | 4h | 11129 | 11101 | 0 | 0 | 11101 | 3330 | 3329 | 0 | 0 | 0 | 26.58 |
| SOL/USDT | 4h | 11129 | 11101 | 0 | 0 | 11101 | 3403 | 3395 | 0 | 0 | 0 | 23.06 |

## Regime distribution per (symbol, timeframe)

- **BTC/USDT 1h**: {'SIDEWAYS': 19081, 'TREND_UP': 8247, 'TREND_DOWN': 8152}
- **ETH/USDT 1h**: {'SIDEWAYS': 17128, 'TREND_UP': 9033, 'TREND_DOWN': 9319}
- **BNB/USDT 1h**: {'TREND_DOWN': 8520, 'SIDEWAYS': 18664, 'TREND_UP': 8296}
- **SOL/USDT 1h**: {'SIDEWAYS': 15513, 'TREND_DOWN': 10252, 'TREND_UP': 9682, 'HIGH_VOLATILITY': 33}
- **BTC/USDT 4h**: {'TREND_UP': 3173, 'SIDEWAYS': 4890, 'TREND_DOWN': 3038}
- **ETH/USDT 4h**: {'TREND_UP': 3278, 'SIDEWAYS': 4661, 'TREND_DOWN': 3162}
- **BNB/USDT 4h**: {'TREND_UP': 3124, 'SIDEWAYS': 4888, 'TREND_DOWN': 3089}
- **SOL/USDT 4h**: {'TREND_UP': 3229, 'SIDEWAYS': 4391, 'TREND_DOWN': 3372, 'HIGH_VOLATILITY': 109}

## Integrity summary

- Total lineage violations across all 8 (symbol, timeframe) series: **0**
- Total leakage violations: **0**
- Total duplicate candidates: **0**

Zero across all three is the expected, required result — any non-zero value here indicates a real wiring bug, not a strategy quality issue, and must be fixed before this pipeline is used for anything downstream.

## Sanity-checking the gap/stale numbers against Phase 0.1's real gap

1h data has exactly 1 real missing candle (`gap_count=1` in `TIMEFRAME_DATA_QUALITY_REPORT.json`). With `feature_lookback_bars=250` (`TimeframeConfig` for 1h), every decision point whose 250-bar lookback window includes that single missing candle is invalidated — exactly 250 dropped-by-gap-policy points, which is exactly what all four 1h series show. With `label_horizon=24h` (24 bars), 25 decision points fall in the corresponding label-horizon-contaminated window (`dropped_by_stale_policy=25`). 4h data has `gap_count=0`, so both counts are correctly 0. These numbers are a direct, mechanical consequence of the real gap found and documented in Phase 0.1 — not independently estimated.

## Note on candidate counts vs. a real backtest's trade count

This dry run proposes a candidate at **every** valid, non-NO_TRADE decision point, independent of whether a hypothetical position would still be open — unlike `packages/backtest/engine.py`, which only asks `DecisionService` for a new decision when flat. That's why candidate counts here (e.g. 9,327 for BTC/USDT 1h) are far higher than a comparable backtest's trade count would be: this measures "how often would the pipeline produce a candidate if asked," not "how many trades a portfolio would actually take." No fills, no PnL, no position tracking — by design, per the Master Plan's "no ML training yet" scope for this phase.
