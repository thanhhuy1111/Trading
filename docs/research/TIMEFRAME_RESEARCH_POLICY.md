# Timeframe Research Policy

## Scope

Checkpoint 2 extends the research pipeline from 1D-only (Checkpoint 1) to 1h and 4h, for:

```
Symbols: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT
Timeframes: 1h, 4h
Target coverage: 1h >= 4 years, 4h >= 5 years (if available from the data source)
```

## Data acquisition

`packages/research/data_fetcher.py: load_or_fetch_resumable` — same real public Binance data
mirror (`data-api.binance.vision`) already used for 1D in Checkpoint 1, extended with resume
support: progress checkpoints to a `.partial.json` sidecar after every fetched page, so an
interrupted multi-thousand-candle fetch resumes rather than restarting (`tests/unit/
test_data_fetcher_resume.py`). Only closed candles are kept (`is_closed=True` and
`close_time <= as_of`, enforced in `validate_historical_series`, not at fetch time — the
mirror can return an in-progress final candle depending on request timing, so filtering
happens after fetch, not instead of it). Fetched data is cached under `data/research/` —
gitignored, never committed, regenerable by re-running the fetch.

Real acquisition run: `python -m packages.research.fetch_timeframe_datasets`, output at
`docs/research/experiments/TIMEFRAME_DATA_QUALITY_REPORT.json`.

## Why 1h and 4h need their own config — not 1D's

`packages/backtest/timeframe_config.py: TimeframeConfig`, one independently-set instance per
timeframe (`get_timeframe_config` raises `KeyError` for anything without an explicit entry —
no silent "closest timeframe" fallback):

| Field | 1D | 4h | 1h | Why it must differ |
|---|---|---|---|---|
| `feature_lookback_bars` | 250 | 250 | 250 | Kept equal — this exists to satisfy indicator lookback (max 28 bars for standard_v1), a property of the indicators, not of calendar time |
| `label_horizon` | 10 days | 48h (~2d) | 24h (~1d) | A realistic swing-trade horizon scales with the timeframe itself |
| `upper_barrier_pct` / `lower_barrier_pct` | 5% / 3% | 2.23% / 1.34% | 1.58% / 0.95% | sqrt-time-scaled down from the 1D baseline (`packages/agents/strategy_config.py`'s existing `trend_take_profit_pct`/`trend_stop_pct`), a standard volatility-scaling heuristic — not fit to any backtest result |
| `purge_period` / `embargo_period` | 10 days | 48h | 24h | Set to exactly 1x `label_horizon` — the actual statistical requirement for walk-forward CV (remove samples whose label window can overlap the train/test boundary), not an arbitrary constant |
| `estimated_fee_bps` / `spread` / `slippage` | 10 / 2 / 5 | 10 / 2 / 5 | 10 / 2 / 5 | Deliberately identical — these reflect the exchange fee schedule and market microstructure, not candle aggregation |
| `minimum_trade_count` | 20 | 30 | 50 | Higher for higher-frequency timeframes: trades close together in time on 1h data are less statistically independent than on 1D, so the same raw count is weaker evidence |
| `proposal_expiry` | 1 day | 4h | 1h | One bar — after the next bar closes, the features/regime a proposal was computed from are stale |

## Gap policy

See `DATA_QUALITY_POLICY.md` — gap classification (feature-lookback-window vs.
label-horizon-window impact) uses each timeframe's own `feature_lookback`/`label_horizon`
from this config, so the same calendar gap can invalidate a different set of decision points
on 1h vs. 1D data. That's intentional, not an inconsistency.

## What Checkpoint 2 does NOT do with this data

The 1h/4h datasets fetched this checkpoint are validated (real quality reports produced) but
**not** yet run through a full walk-forward campaign (that's Checkpoint 4's Campaign V2, scoped
explicitly for later) and **not** used to train any ML model (Checkpoint 3). This checkpoint's
job was building and proving the acquisition/validation/regime/routing pipeline works
end-to-end — see `docs/research/CHECKPOINT_2_REPORT.md` for what was actually run and verified.
