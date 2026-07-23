# Historical Dataset Data Quality Policy (Research)

This document covers **historical series validation** for research datasets (1h/4h/1D candle
series pulled for backtesting/campaign use). It is distinct from and complements
`docs/DATA_QUALITY_POLICY.md`, which covers **live streaming** record-by-record validation
(`packages/market_data/guardian.py: DataGuardian`) — freshness, single-trade/candle validity,
crossed order books. A historical dataset needs series-level checks that only make sense with
the whole sequence in hand: duplicate timestamps, out-of-order candles, missing candles
(gaps), and interval-spacing consistency. That's what
`packages/market_data/historical_quality.py` implements.

## Checks performed (`validate_historical_series`)

Every defect below is **removed** from the returned clean series, not merely flagged and left
in — the caller never has to separately filter what the report counted:

| Check | What it catches |
|---|---|
| Duplicate timestamp | Two candles with the same `close_time` |
| Out-of-order candle | A candle that sorts before its predecessor after tie-breaking |
| Invalid OHLC | `high < max(open,close,low)`, `low > min(open,close,high)`, non-positive prices |
| Negative volume | `volume < 0` |
| Not-yet-closed candle | `is_closed == False` |
| Future timestamp | `close_time > as_of` (the point-in-time cutoff the caller supplies) |
| Wrong interval spacing | Consecutive candles not spaced by an exact multiple of the timeframe's interval |

No forward-fill, ever — a gap stays represented as a gap (`GapRecord`), never synthesized.

## Gap policy

A gap's impact depends on *where* it falls relative to a specific decision point, not just
whether it exists:

```text
Gap inside [t - feature_lookback, t]:
  -> contaminates the features used to decide at t
  -> that decision point is INVALID (GAP_IN_FEATURE_LOOKBACK)

Gap inside [t, t + label_horizon]:
  -> contaminates the realized outcome used to label the decision made at t
  -> that decision point is INVALID (GAP_IN_LABEL_HORIZON)

Gap outside both windows:
  -> doesn't affect this specific decision point

Gap exceeding 10% of a segment's expected candle count (SEVERE_GAP_FRACTION):
  -> the whole segment/dataset is REJECTED, not just DEGRADED
```

Implemented by `filter_valid_decision_points` (per-decision-point validity, given a list of
candidate decision timestamps and the gap list) and the `DatasetQualityStatus`
(`VALIDATED` / `DEGRADED` / `REJECTED`) computed by `validate_historical_series` itself for the
whole series.

`feature_lookback` and `label_horizon` are **not** universal constants — they come from
`packages/backtest/timeframe_config.py: TimeframeConfig`, which is explicitly different per
timeframe (see `TIMEFRAME_RESEARCH_POLICY.md`). A gap that's harmless for 1D's 10-day label
horizon could invalidate a much larger fraction of 1h decision points, whose label horizon is
only 24 hours — that's expected and correct, not a bug.

## Where this plugs into the dataset registry

`packages/backtest/datasets.py: DatasetRegistry.register_dataset` previously always computed
`gap_count = 0` (a stub — the field existed but the value was never actually derived from the
candles). It now computes real gap counts for single-timeframe datasets using the same
interval table (`TIMEFRAME_INTERVAL`), so `quality_status` reflects reality. This changes
nothing for existing gap-free test fixtures (verified — see `tests/unit/test_backtest_safety.py`).

## Real result: 1h/4h acquisition (Checkpoint 2)

See `docs/research/experiments/TIMEFRAME_DATA_QUALITY_REPORT.json` for the actual, real
quality report produced by running `validate_historical_series` against the real 1h/4h candles
fetched for BTC/ETH/BNB/SOL (`python -m packages.research.fetch_timeframe_datasets`).
