# ALPHA RESEARCH — LABELING

`packages/research/labels.py::build_label_table`. Cost-aware triple-barrier labels,
long-only, spot.

## 1. Barrier definitions

For an entry at candle `i` (`entry_time = candle[i].close_time`,
`entry_reference_price = candle[i].close_price`):

```
upper_barrier = entry_reference_price * (1 + upper_barrier_pct)
lower_barrier = entry_reference_price * (1 - lower_barrier_pct)
time_barrier  = entry_time + horizon_minutes
```

The forward candle sequence (`candle[i+1:]`) is walked until one of the three barriers is
touched, using each candle's `high_price`/`low_price` (not just `close_price`) to detect
an intrabar touch — this is deliberately more realistic than checking closes only.

**Same-candle both-barriers tie-break:** if a single forward candle's `high >= upper` AND
`low <= lower`, `LOWER` is assumed hit first. OHLC alone cannot reveal true intrabar path;
assuming the favorable outcome would systematically bias every ambiguous case toward
profit, which is not conservative.

## 2. Label semantics

| `first_barrier_hit` | `label` |
|---|---|
| `LOWER` | `LOSS` (always — a lower-barrier touch cannot become "profit" after costs) |
| `UPPER` | `PROFIT` if `net_return_bps > 0`, else `LOSS` |
| `TIME` (no barrier touched by `time_barrier`) | `TIMEOUT`, regardless of sign |

The `UPPER → LOSS` case is intentional and is the entire point of computing costs BEFORE
labeling, not after: a barrier distance smaller than the round-trip cost is not a real
profit opportunity even though price technically moved the "right" direction.
`test_labels_cost_can_flip_small_upper_touch_to_loss` proves this with a 10bps barrier
against a ~22bps BTCUSDT round-trip cost.

`TIMEOUT` is a distinct third class, not folded into PROFIT/LOSS by sign — matching the
literal triple-barrier method (López de Prado, *Advances in Financial Machine Learning*,
ch. 3): "the position was closed by the clock, not by a barrier" is itself meaningful
information for a classifier to learn from, and conflating it with LOSS would tell the
model that "went nowhere" and "went the wrong way" are the same outcome, which they are not.

## 3. Cost model

Costs are estimated via the EXISTING `packages.governance.cost_estimator.cost_estimator`
— the same conservative fee (10bps) + spread (2bps BTC / 4bps other) + slippage (5bps) +
uncertainty buffer (5bps) model the live paper-trading path and
`packages.recommendation.cost_service` both already use. This module does not define its
own cost assumptions.

```
gross_return_bps = (exit_price - entry_reference_price) / entry_reference_price * 10000
net_return_bps   = gross_return_bps - estimated_cost_bps
```

## 4. No-leakage guarantee

A label is computed entirely from candles `>= entry_time` — this is the ONE place in the
pipeline allowed to look forward, because that is definitionally what a label is. The
guarantee under test (`tests/unit/test_research_features_labels.py`) is architectural
separation, not just "the math happens to be right": `packages/research/labels.py` never
imports `packages/research/feature_dataset.py` or `feature_pipeline`, and vice versa
(`test_labels_module_never_imports_feature_dataset`,
`test_feature_dataset_module_never_references_label_concepts`) — a feature literally
cannot reach a label's data even by accident.

An entry too close to the end of the available candle history to reach its
`horizon_minutes` is **skipped entirely**, never partially labeled or guessed
(`test_labels_skip_entries_without_enough_forward_history`).

## 5. Recorded fields per observation

`entry_reference_price`, `upper_barrier`, `lower_barrier`, `time_barrier`,
`first_barrier_hit`, `gross_return_bps`, `estimated_cost_bps`, `net_return_bps`, `label`,
`label_end_time` — every field the implementation plan requires, all in one row, so a
label's full derivation is auditable without recomputation.

## 6. Known limitations

- Barrier percentages are symmetric and static per run (`upper_barrier_pct` /
  `lower_barrier_pct` in `LabelConfig`), not volatility-scaled (e.g. ATR-multiple
  barriers). A fixed-percentage barrier is easier to reason about and audit but is less
  realistic across regimes of very different volatility — a future version could make
  barriers a function of `atr_14` at entry time.
- Costs are the same conservative constants used everywhere else in this repository, not
  fit from realized fill data (none exists yet — see
  `docs/AI_TRADING_ADVISOR_ARCHITECTURE.md` known gaps).
