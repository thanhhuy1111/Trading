# ALPHA RESEARCH — DATASET PIPELINE

## 1. Data source and semantics

- **Source:** Binance public Spot REST API (`packages.market_data.adapters.binance
  .BinancePublicMarketDataProvider`), via `MarketDataProviderFactory.create_provider
  ("binance")`. No private API key, no user data endpoints — the same adapter the live
  paper-trading and recommendation paths use.
- **Canonical identity:** a candle's `open_time` is its identity. Deduplication
  (`packages.research.dataset_builder.build_raw_candle_dataset`) keys on
  `(symbol, timeframe, open_time)`.
- **Timezone:** UTC everywhere, enforced by `Candle`'s own Pydantic validator
  (`exchange_timestamp`/`received_timestamp` must be tz-aware) and by
  `packages.backtest.datasets.DatasetRegistry.register_dataset`'s check.

## 2. Candle-close policy

Only **closed** candles are used to build training data (`c.is_closed`). On top of that,
`build_raw_candle_dataset` independently drops any candle whose `close_time` is still in
the future relative to wall-clock `now` — the same defensive check
`packages.recommendation.service.RecommendationService._fetch_candles` added after a real
bug was found there: `BinancePublicMarketDataProvider` marks every returned kline
`is_closed=True`, including the currently-forming one. Trusting `is_closed` alone would
let a not-yet-closed candle enter training data.

## 3. Validation and rejection policy

`build_raw_candle_dataset` (`packages/research/dataset_builder.py`) rejects — never
silently repairs — a candle for any of:

| Condition | Action |
|---|---|
| Symbol not in the dataset config's `symbols` | rejected, counted |
| Timeframe not in the dataset config's `timeframes` | rejected, counted |
| Not closed | rejected, counted |
| `close_time` in the future | rejected, counted |
| Invalid OHLC relationship | rejected, counted (via `packages.market_data.guardian.data_guardian.validate_ohlc` — the SAME check the live path uses) |
| Negative volume | rejected, counted (defense-in-depth; `Candle`'s own validator already forbids this at construction) |
| Duplicate `(symbol, timeframe, open_time)` | first occurrence kept, rest counted as duplicates |
| Gap in expected spacing (> 1.5x the timeframe interval) | **not removed**, counted informationally |

**No forward-filling of any kind is performed anywhere in this pipeline.** A missing
candle stays missing. Silently forward-filling a price would let a stale observation
masquerade as a fresh one — exactly the failure mode `packages.market_data.guardian`
already exists to prevent on the live path.

If, after rejection, zero candles remain, `build_raw_candle_dataset` raises
`DatasetValidationError` rather than returning an empty, silently-unusable dataset.

## 4. Reproducibility and checksums

`build_raw_candle_dataset` reuses `packages.backtest.datasets.dataset_registry
.compute_dataset_checksum` — the exact SHA-256 scheme backtest sessions already use — so a
research dataset and a backtest dataset built from identical candles produce identical
checksums. The checksum is computed AFTER sorting canonically
(`(symbol, timeframe, open_time)`), because the underlying checksum function hashes
candles in the order given, not sorted order (`test_checksum_candles_is_order_sensitive_
so_dataset_builder_sorts_first` documents this explicitly).

Every `RawCandleDataset` artifact records: `dataset_id`, `dataset_checksum`, `symbols`,
`timeframes`, `start_time`, `end_time`, `candle_count`, `source`, `source_version`,
`created_at`, `code_commit` (best-effort `git rev-parse HEAD`, never fatal if unavailable),
`config_hash`, `duplicate_count`, `rejected_count`, `quality_status`
(`VALIDATED`/`DEGRADED`), `quality_issues`.

## 5. Storage layout

```
data/research/candles/{SYMBOL}_{timeframe}.parquet       raw download cache (mutable)
data/research/candles/{SYMBOL}_{timeframe}.checkpoint.json  resume checkpoint
artifacts/datasets/{dataset_id}.json                      RawCandleDataset metadata
artifacts/datasets/{dataset_id}.parquet                   validated candle table
```

Both directories are gitignored; no market data is ever committed to this repository.

## 6. Historical download

`packages.research.candle_repository.CandleRepository` wraps the EXISTING
`packages.market_data.ingestion.historical.HistoricalCandleIngestionService` — bounded
pagination, rate-limit spacing, retry/backoff, and closed-candle filtering are all reused,
not reimplemented. `CandleRepository` adds local Parquet persistence and checkpoint/resume
so re-running `download-data` continues from `last_ingested_open_time` instead of
re-fetching the whole range.

The default test suite never downloads data — see docs/ALPHA_RESEARCH_TESTING section in
`docs/AI_TRADING_ADVISOR_TESTING.md`'s sibling coverage and
`tests/unit/test_research_cli.py` for the offline `--dry-run` proof.

## 7. Known limitations

- Gap detection is informational only; a dataset with material gaps still builds
  (`quality_status=DEGRADED`), it is not blocked. Downstream feature/label quality for
  gappy regions is not separately flagged.
- No order-book data is ingested (per implementation plan section 6: "Do not add
  order-book features unless historical order-book data is actually available and
  point-in-time correct" — it is not, so none were added).
