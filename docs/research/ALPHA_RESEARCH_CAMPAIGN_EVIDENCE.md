# Full Alpha Research Campaign — Evidence Report

_Generated: 2026-07-23T13:02:52.867901+00:00 | git: 1169172b96d58ebeff8558af2a1e16250d544930_

This report is generated exclusively from real out-of-sample walk-forward results produced by `packages/research/campaign.py` running the production `EventDrivenBacktestEngine`. See `docs/research/ALPHA_RESEARCH_GATE.md` for the exact promotion-gate criteria and `docs/research/experiments/` for the full, unfiltered experiment ledger (every run, pass or fail).

## Result: NO STRATEGY CONFIGURATION CLEARED THE GATE

No (symbol, config) pair in this campaign passed the promotion gate on **both** BTC/USDT and ETH/USDT out-of-sample walk-forward folds. Per campaign policy, **no strategy evidence is published** — this section exists precisely to avoid publishing evidence for something that did not actually clear the gate.

### Closest near-misses (for context only — NOT promoted, NOT for paper/live use)

| Symbol | Config | Passed | Reasons | OOS Trades | Profitable Folds | Mean OOS Sharpe | Worst Fold DD % | Aggregate Net PnL |
|---|---|---|---|---|---|---|---|---|
| BTC/USDT | reversion_loose_bands | True | - | 30 | 2/3 | 0.9994333333333333333333333333 | 1.252620685653641909281221391 | 3594.818190850620000000 |
| BTC/USDT | momentum_focus | True | - | 35 | 2/3 | 0.8519 | 1.853343793900156478948578546 | 3406.476544382670000000 |
| BTC/USDT | trend_confidence_high | True | - | 35 | 2/3 | 0.8114666666666666666666666667 | 1.981734020109928922384351428 | 3401.071063848000000000 |
| BTC/USDT | reversion_tight_bands | True | - | 36 | 2/3 | 0.7815333333333333333333333333 | 1.781099714324905167100639389 | 2908.501723093830000000 |
| BTC/USDT | low_conviction_admitted | True | - | 35 | 2/3 | 0.7668 | 1.566318947844460498336159141 | 2491.752184012020000000 |
| BTC/USDT | wide_risk_structure | True | - | 35 | 2/3 | 0.7646 | 1.307374265280137253121526810 | 2064.110782233990000000 |
| BTC/USDT | breakout_strict | True | - | 35 | 2/3 | 0.7643 | 1.814306822600813584767665450 | 2859.681771002775000000 |
| BTC/USDT | baseline | True | - | 35 | 2/3 | 0.7635333333333333333333333333 | 1.814306822600813584767665450 | 2857.930963028355000000 |
| BTC/USDT | tight_risk_structure | True | - | 35 | 2/3 | 0.7613 | 2.557437364949641122653512579 | 4010.608026145260000000 |
| BTC/USDT | high_conviction_only | True | - | 35 | 2/3 | 0.7584 | 2.062986416878662379352939160 | 3229.024686966090000000 |

