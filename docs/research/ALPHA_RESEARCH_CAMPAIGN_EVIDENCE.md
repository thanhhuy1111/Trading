# Full Alpha Research Campaign — Evidence Report

_Generated: 2026-07-23T16:56:29.636601+00:00 | git: 3787e816fa67ecc7d75273bbd0cf23992544d02d_

This report is generated exclusively from real out-of-sample walk-forward results produced by `packages/research/campaign.py` running the production `EventDrivenBacktestEngine`. See `docs/research/ALPHA_RESEARCH_GATE.md` for the exact promotion-gate criteria and `docs/research/experiments/` for the full, unfiltered experiment ledger (every run, pass or fail).

## Result: NO STRATEGY CONFIGURATION CLEARED THE GATE

No (symbol, config) pair in this campaign passed the promotion gate on **both** BTC/USDT and ETH/USDT out-of-sample walk-forward folds. Per campaign policy, **no strategy evidence is published** — this section exists precisely to avoid publishing evidence for something that did not actually clear the gate.

### Closest near-misses (for context only — NOT promoted, NOT for paper/live use)

| Symbol | Config | Passed | Reasons | OOS Trades | Profitable Folds | Mean OOS Sharpe | Worst Fold DD % | Aggregate Net PnL | Deflated Sharpe Ratio | PBO |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC/USDT | reversion_loose_bands | True | - | 30 | 2/3 | 0.9778333333333333333333333333 | 1.252620685653641909281221391 | 3558.320595679920000000 | 0.982825 | 0.0 |
| BTC/USDT | momentum_focus | True | - | 35 | 2/3 | 0.8311333333333333333333333333 | 1.853343793900156478948578546 | 3366.484498610520000000 | 0.951939 | 0.0 |
| BTC/USDT | trend_confidence_high | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.93053<0.95 | 35 | 2/3 | 0.7909 | 1.981734020109928922384351428 | 3359.914201208700000000 | 0.93053 | 0.0 |
| BTC/USDT | reversion_tight_bands | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.913312<0.95 | 36 | 2/3 | 0.7615 | 1.781099714324905167100639389 | 2872.004127923130000000 | 0.913312 | 0.0 |
| BTC/USDT | low_conviction_admitted | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.898146<0.95 | 35 | 2/3 | 0.7466333333333333333333333333 | 1.566318947844460498336159141 | 2460.302128598970000000 | 0.898146 | 0.0 |
| BTC/USDT | wide_risk_structure | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.896144<0.95 | 35 | 2/3 | 0.7443 | 1.307374265280137253121526810 | 2037.708266578590000000 | 0.896144 | 0.0 |
| BTC/USDT | breakout_strict | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.895884<0.95 | 35 | 2/3 | 0.7440 | 1.814306822600813584767665450 | 2823.184175832075000000 | 0.895884 | 0.0 |
| BTC/USDT | baseline | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.895305<0.95 | 35 | 2/3 | 0.7433333333333333333333333333 | 1.814306822600813584767665450 | 2821.433367857655000000 | 0.895305 | 0.0 |
| BTC/USDT | tight_risk_structure | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.893377<0.95 | 35 | 2/3 | 0.7411333333333333333333333333 | 2.557437364949641122653512579 | 3959.356083990660000000 | 0.893377 | 0.0 |
| BTC/USDT | high_conviction_only | False | DEFLATED_SHARPE_RATIO_BELOW_MIN:0.890791<0.95 | 35 | 2/3 | 0.7382333333333333333333333333 | 2.062986416878662379352939160 | 3187.867824326790000000 | 0.890791 | 0.0 |

