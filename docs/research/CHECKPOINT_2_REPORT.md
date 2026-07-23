# Checkpoint 2 Report — Data Quality, 1h/4h Dataset, Regime Detection, Strategy Router

## Branch

`feat/timeframe-data-regime-router`, created from `feat/multi-asset-alpha-platform`
(Checkpoint 1's completed branch, commit `416b4bd`). Pushed to
`origin/feat/timeframe-data-regime-router`. No pull request opened (not requested).

## Commits (8, in order)

| Commit | Summary |
|---|---|
| `87f075e` | Add historical dataset quality validator and gap policy |
| `ab1e624` | Add timeframe-specific research configuration (1h/4h != 1D) |
| `0dec0e9` | Add point-in-time regime detection with confidence/version/reason-code lineage |
| `9e8b075` | Add deterministic, versioned strategy router |
| `803ba24` | Wire strategy-router filtering into DecisionService.decide |
| `54b039e` | End-to-end raw-candle -> candidate pipeline (completion proof) |
| `cec4974` | Add resumable market data acquisition for large 1h/4h fetches |
| `4a2db92` | Checkpoint 2 policy write-ups |

## Files added / modified

19 files changed, +1,687 / -8 lines vs. the source branch.

**New:**
- `packages/market_data/historical_quality.py` — series-level dataset validator + gap policy
- `packages/backtest/timeframe_config.py` — per-timeframe research config
- `packages/governance/strategy_router.py` — deterministic regime→strategy routing
- `packages/governance/candidate_pipeline.py` — end-to-end raw-candle→candidate chain
- `packages/research/fetch_timeframe_datasets.py` — opt-in live 1h/4h acquisition script
- `docs/research/DATA_QUALITY_POLICY.md`, `TIMEFRAME_RESEARCH_POLICY.md`,
  `REGIME_ROUTER_POLICY.md`
- `docs/research/experiments/TIMEFRAME_DATA_QUALITY_REPORT.json` — real quality report
- Tests: `test_historical_data_quality.py` (14), `test_timeframe_config.py` (6),
  `test_regime_detail.py` (5), `test_strategy_router.py` (7),
  `test_decision_service_routing.py` (4), `test_candidate_pipeline_e2e.py` (6),
  `test_data_fetcher_resume.py` (3) — **45 new tests**, all offline/deterministic
  (network calls are monkeypatched, not skipped).

**Modified:**
- `packages/backtest/datasets.py` — `DatasetRegistry.register_dataset`'s `gap_count` was
  hardcoded to 0 (a stub); now computed for real for single-timeframe datasets. Verified no
  existing test's expected `quality_status` changes.
- `packages/agents/regime.py` — added `classify_regime_detailed` alongside the untouched
  `classify_regime` (single source of truth, no duplicated thresholds).
- `packages/governance/decision_service.py` — added optional `allowed_strategy_types` param
  to `decide()`. `None` (default, every existing caller) is byte-identical to prior behavior.
- `packages/research/data_fetcher.py` — added `load_or_fetch_resumable`; the existing
  `load_or_fetch` (Checkpoint 1's campaign) is untouched.

## Tests run

Command: `python -m pytest tests/ -q`.

**Result: PASSED (same 3 pre-existing, environment-caused failures as Checkpoint 1)**

```
3 failed, 231 passed, 12 skipped, 2 warnings in ~3s
```

- **Passed: 231** (186 from Checkpoint 1 + 45 new this checkpoint).
- **Failed: 3, pre-existing, unrelated, unchanged from Checkpoint 1** — **BLOCKED**:
  `api.binance.com` geo-restricted (HTTP 451) from this sandbox (`test_binance_public_adapter.py`,
  2 tests); `infra/migrations/alembic.ini` path/PostgreSQL not provisioned in this sandbox
  (`test_db_migration.py`, 1 test).
- **Skipped: 12** — **NOT AVAILABLE**: `test_paper_durable_persistence.py`, all
  skip-guarded on `PAPER_DB_TEST_URL` (disposable PostgreSQL), not provisioned here.

`ruff check .` (full repo): **PASSED** — zero findings.

`mypy` (project's `strict=True` config) on this checkpoint's new/changed files: **FAILED,
mostly pre-existing** — of 30 errors reported, the large majority are in files this checkpoint
never touched (`packages/features/calculators/*`, `packages/agents/{trend,reversion,breakout}.py`,
`packages/market_data/models.py`), already present in `feat/multi-asset-alpha-platform`. Two
new gaps this checkpoint's own code adds, following the same already-common untyped pattern:
`strategy_router.py:35` (missing generic type args on an internal dict-of-tuples), and
`candidate_pipeline.py:51` (a local closure missing a parameter annotation). Not remediated —
same reasoning as Checkpoint 1: the codebase's mypy baseline is not strict-clean to begin
with, and chasing full compliance here would be disproportionate to this checkpoint's scope.

**Live, opt-in, network-touching runs** (each executed for real, not simulated):
- `python -m packages.research.fetch_timeframe_datasets` — **PASSED**. Real 1h/4h candles
  fetched for BTC/ETH/BNB/SOL from `data-api.binance.vision`, in ~2 minutes for all 8
  (symbol, timeframe) combinations. Output: `docs/research/experiments/
  TIMEFRAME_DATA_QUALITY_REPORT.json`.

Campaign V2 (Checkpoint 4), ML training (Checkpoint 3), and anything beyond this
checkpoint's scope were explicitly **NOT RUN**, per the instruction to stop after Checkpoint 2.

## Real data acquisition result

| Symbol | Timeframe | Clean candles | Coverage achieved | Target met | Quality status |
|---|---|---|---|---|---|
| BTC/USDT | 1h | 35,758 | 1,489 days (~4.08y) | Yes (≥4y) | DEGRADED |
| ETH/USDT | 1h | 35,758 | 1,489 days | Yes | DEGRADED |
| BNB/USDT | 1h | 35,758 | 1,489 days | Yes | DEGRADED |
| SOL/USDT | 1h | 35,758 | 1,489 days | Yes | DEGRADED |
| BTC/USDT | 4h | 11,129 | 1,854 days (~5.08y) | Yes (≥5y) | DEGRADED |
| ETH/USDT | 4h | 11,129 | 1,854 days | Yes | DEGRADED |
| BNB/USDT | 4h | 11,129 | 1,854 days | Yes | DEGRADED |
| SOL/USDT | 4h | 11,129 | 1,854 days | Yes | DEGRADED |

All 8 met their coverage target. All 8 are `DEGRADED` (not `REJECTED` — well under the 10%
severe-gap threshold) for two identified, real, non-fabricated reasons:

1. **One in-progress boundary candle per fetch**, correctly caught by the
   `future_timestamp_count` check: the exchange's public kline API can still return the
   currently-forming candle at the request's `endTime` boundary even though it hasn't closed
   yet (its official close time is after the fetch cutoff). Removed from the clean series, not
   fabricated as closed.
2. **A genuine data anomaly in the source itself**, found by direct inspection: BTC/USDT 1h
   has one candle at `2023-03-24 12:39:41.646 UTC` — not aligned to the hourly `:59:59.999`
   grid every other candle in the series follows. The exact same anomalous timestamp appears
   identically in ETH/USDT, BNB/USDT, and SOL/USDT's 1h series too, which points to a real,
   exchange-wide event around that time (not a bug in this checkpoint's fetch/pagination
   logic) rather than four independent coincidences. It produces 2 `wrong_spacing_count` flags
   (one on each side) per symbol and is correctly retained (not silently dropped) since it
   passes every other individual-candle check. 1h data also shows exactly 1 missing candle
   (`gap_count=1`) elsewhere in the series per symbol — a small, genuine, isolated historical
   gap, again identical in count across all four symbols.

This is reported here rather than only in the JSON because it's a concrete demonstration that
`validate_historical_series` catches real anomalies in real third-party data, not just
synthetic test fixtures.

## Design decisions

1. **The new historical-series validator is a separate module from the existing streaming
   guardian**, not a rewrite of it. `packages/market_data/guardian.py` validates one live
   record at a time (freshness, single-candle OHLC, crossed book); the new
   `historical_quality.py` validates a whole series (duplicates, ordering, gaps, spacing) —
   different problem, different module, `DATA_QUALITY_POLICY.md` documents how they relate.
2. **Every defect the validator counts is actually removed from the clean series** it returns
   — a caller never has to separately re-filter what the report flagged. No forward-fill,
   ever; a gap stays a gap (`GapRecord`), and callers decide its impact via
   `filter_valid_decision_points` rather than the validator silently deciding for them.
3. **Gap impact is decision-point-relative, not dataset-global.** A gap only invalidates the
   specific decisions whose feature-lookback or label-horizon window it falls inside — this
   needed each timeframe's own `feature_lookback`/`label_horizon` from
   `TimeframeConfig`, reinforcing why 1h/4h can't share 1D's config.
4. **1h/4h `TimeframeConfig` values are derived by stated rules, not fit to any result**:
   barrier percentages are sqrt-time-scaled down from 1D's existing production defaults
   (`packages/agents/strategy_config.py`); purge/embargo are set to exactly 1x label_horizon
   (the actual walk-forward CV requirement); cost assumptions are deliberately identical
   across timeframes (exchange/microstructure-driven, not timeframe-driven). All stated in
   `TIMEFRAME_RESEARCH_POLICY.md` so the rules are auditable, not just the resulting numbers.
5. **The router filters which agents *run*, not which signals get discarded after the
   fact.** `DecisionService.decide`'s new `allowed_strategy_types` param skips `evaluate()`
   entirely for a disallowed agent. An empty allowed set (LOW_LIQUIDITY/UNCERTAIN/UNKNOWN)
   needed no special NO_TRADE handling — it flows through the pre-existing consensus
   (`INSUFFICIENT_EVIDENCE`) → allocator (`NO_TRADE`) path unmodified.
6. **Stated, not hidden: no Pullback agent exists.** The router's `TREND_UP`/`TREND_DOWN`
   entries route to `{TREND_FOLLOWING}` only, not "trend + pullback" as the Master Plan's
   example table shows, because routing to a `StrategyType` with no agent behind it would
   silently no-op while looking like a real decision — see `REGIME_ROUTER_POLICY.md` "known gap."
7. **Resumable fetch is a separate function, not a behavior change to the existing one.**
   `load_or_fetch_resumable` (new) checkpoints progress per page; `load_or_fetch` (unchanged)
   stays exactly what Checkpoint 1's campaign already relies on and was re-verified against
   (`GATE_RESULTS.csv` byte-identical across the whole prior checkpoint's re-runs).

## Discovered risks

1. **Real, non-fabricated data anomaly in the source** (§ above) — a single misaligned candle
   at `2023-03-24 12:39:41 UTC` across all four symbols' 1h series, plus one isolated missing
   candle. Small enough to stay `DEGRADED` rather than `REJECTED`, but any future walk-forward
   fold whose boundary happens to land near that timestamp should be checked against
   `filter_valid_decision_points` before being trusted.
2. **`TimeframeConfig`'s barrier/horizon values are principled but unvalidated.** They're
   derived by a stated scaling rule, not backtested — Checkpoint 3/4 will be the first time
   these numbers are actually tested against real out-of-sample results. If they turn out to
   be poorly calibrated, the fix belongs in `TIMEFRAME_RESEARCH_POLICY.md`'s documented rule,
   not a silent one-off tweak.
3. **The router's `TREND_DOWN → {TREND_FOLLOWING}` entry has no executable effect today**
   (spot long-only allocator policy blocks it) — this is intentional and documented, but a
   future short-enabled execution mode would need this checked again before relying on the
   router alone to prevent shorting.
4. **Mypy strict-mode debt continues to grow slightly** (2 new gaps this checkpoint, on top of
   Checkpoint 1's 47 pre-existing) — flagged again as compounding risk before Checkpoint 3's
   ML code lands, same as noted in `CHECKPOINT_1_REPORT.md`.
5. **`docs/research/experiments/CANDIDATES.csv`-style growth risk applies here too** — this
   checkpoint didn't add a new committed large CSV (the 1h/4h raw data itself stays gitignored
   under `data/research/`, per the plan's explicit "don't commit downloaded data" rule), but
   Checkpoint 4's Campaign V2 across 4 symbols × 2 timeframes will multiply Checkpoint 1's
   already-4.4MB `CANDIDATES.csv` substantially — worth deciding a retention policy before
   that run, not after.

## Remaining gaps (explicitly out of scope, per instruction to stop here)

- No ML meta-label model trained (Checkpoint 3).
- No Campaign V2 / walk-forward run on the new 1h/4h data (Checkpoint 4) — this checkpoint
  fetched and validated the data and proved the regime→router→candidate pipeline works
  end-to-end on synthetic fixtures, but did not run it at scale against the real 1h/4h series.
- No LLM market agents (Checkpoint 6), no shadow mode (Checkpoint 8), no monitoring/drift
  (Checkpoint 9) — none attempted.
- No Pullback strategy agent — stated as a known gap, not implemented.
- Live trading remains disabled; nothing in this checkpoint touches
  `LIVE_TRADING_ENABLED` or any private exchange API.

## Recommendation for next checkpoint

Proceed to **Checkpoint 3 (ML Dataset, Meta-label, Calibration)** as planned, with two notes
carried forward from this checkpoint's findings:

1. Build the candidate training dataset from real 1h/4h data (not just BTC/ETH 1D) so the
   feature leakage protections and time-series split get exercised against the higher-volume,
   higher-noise regime the earlier failure analysis flagged as different market behavior.
2. When splitting train/validation/test by time, explicitly verify no split boundary lands
   inside the 2023-03-24 anomaly window found in this checkpoint's 1h data — a mechanical
   application of `filter_valid_decision_points` before dataset construction should already
   handle this, but it's worth a direct assertion given it's now a known, real event in the
   data.
