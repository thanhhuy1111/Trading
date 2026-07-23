# ALPHA RESEARCH — WALK-FORWARD VALIDATION

## 1. Split methodology

`packages/research/splits.py` wraps `packages.backtest.walk_forward.walk_forward_runner
.generate_folds` — the SAME fold-generation logic backtest walk-forward sessions already
use, not a second implementation. A plain (non-walk-forward) chronological train/
validation/test split is exactly `num_folds=1` of the same generator
(`plan_chronological_split`).

No random shuffling anywhere: splits are strictly chronological, `train.end <=
validation.start <= validation.end <= test.start <= test.end` within every fold
(`test_plan_walk_forward_windows_windows_are_chronological_within_a_fold`).

## 2. Purge and embargo

A label's outcome is only known at `label_end_time`, which can be up to
`max(horizons_minutes)` after its `entry_time`. If the purge gap between train and
validation were shorter than the longest configured label horizon, a label entered near
the end of the training window could have its *outcome* determined by candles inside the
validation window — the model would effectively be validated partly on its own training
signal.

`effective_purge_hours()` therefore **never trusts a configured `purge_hours` smaller
than the longest label horizon** — it silently widens it (and this is a real,
tested behavior: `test_effective_purge_hours_widens_when_config_too_small`), not merely a
comment telling the operator to configure it correctly.

The literal invariant under test (implementation plan section 8), on real labeled data,
not just window boundaries:

```
max(train label_end_time)      < validation.start
max(validation label_end_time) < test.start
```

`packages.research.splits.verify_purge_embargo` asserts exactly this, and
`test_verify_purge_embargo_detects_leaking_train_label` proves the check actually catches
a constructed violation (a train-split label whose `label_end_time` reaches past
`validation.start`), not just that it passes on well-formed input.

## 3. Metrics — what they mean and what they don't

`packages/research/evaluation.py::compute_trade_metrics` computes, per subject (model or
baseline) per split: `trade_count`, `win_rate`, `net_pnl_bps`, `average_net_return_bps`,
`expectancy_bps`, `profit_factor`, `sharpe`, `sortino`, `calmar`, `max_drawdown_pct`,
`turnover`, `total_fees_bps`, `average_holding_minutes`.

**Sharpe/Sortino/Calmar are computed per-trade, NOT annualized.** Triple-barrier trade
events are irregularly spaced in time (a `TIMEOUT` can end far later than a barrier
touch), so a fixed "periods per year" annualization factor would misrepresent
risk-adjusted return for this data shape. Treat these as *relative* comparison statistics
across baselines/models/folds evaluated on the SAME dataset, not as numbers comparable to
an annualized Sharpe reported elsewhere.

**`max_drawdown_pct`** is computed on a synthetic, unit-sized, cumulative-bps equity curve
(each taken trade contributes its `net_return_bps`, summed in entry-time order). This
approximates the drawdown of a strategy that risks a constant unit per trade and
reinvests nothing — a real, if simplified, risk statistic. It is **not** a NAV-based
equity-curve drawdown like `packages.backtest.metrics.PerformanceMetricsEngine` computes
for a real position-sized backtest session; the two are not directly comparable.

`compute_classification_metrics` (precision/recall/F1/ROC-AUC/Brier/log-loss) only
applies to a MODEL (which has a probability column) — baselines produce a boolean
decision, never a probability, so these fields stay `None` for them rather than being
fabricated.

## 4. Breakdowns

Every `EvaluationReport` includes breakdowns by `symbol`, `timeframe`, `regime` (the SAME
`MarketRegimeAgent` classification `packages.research.baselines` already computes while
evaluating the agent baselines — not a second classification pass), `probability_bucket`
(model only), and `window` (one entry per walk-forward fold, so a strategy that only
profits in a single fold is visible, not averaged away — this feeds directly into the
single-window-concentration evidence check, see `docs/ALPHA_EVIDENCE_POLICY.md`).

## 5. Baselines

All six mandatory baselines (`packages/research/baselines.py`) call the REAL agent /
`DecisionService` code, not a re-implementation:

| Baseline | Implementation |
|---|---|
| `NO_TRADE` | trivial, never enters |
| `BUY_AND_HOLD` | trivial, always enters |
| `TREND_ONLY` | real `packages.agents.trend.TrendAgent`, run through the real `FeaturePipeline` |
| `MEAN_REVERSION_ONLY` | real `packages.agents.reversion.MeanReversionAgent` |
| `BREAKOUT_ONLY` | real `packages.agents.breakout.BreakoutAgent` |
| `MULTI_AGENT_NO_ML` | `packages.governance.decision_service.decision_service.decide()` directly — the exact real agents→critic→consensus→allocator chain production already uses |

Every baseline (and the model) is evaluated through the SAME cost-aware label table
(`packages.research.labels`) — comparing a cost-aware model against a cost-free baseline
would be meaningless, so there is no code path that does that.

## 6. Known limitations

- Walk-forward fold count in any given run is small (2-5 typically, given realistic data
  volumes) — per-fold statistics are noisy at that count; treat the `window` breakdown as
  a diagnostic (is any single fold doing all the work?), not as a precise per-window
  estimate.
- `turnover` is currently just the trade count, not a notional-weighted turnover measure.
