# Checkpoint 1 Report — Multi-Asset Alpha Platform Evolution

## Branch

`feat/multi-asset-alpha-platform`, created from `claude/full-alpha-research-campaign-joszu3`
(commit `44dbb44`). Pushed to `origin/feat/multi-asset-alpha-platform`. No pull request opened
(not requested).

## Commits (5, in order)

| Commit | Summary |
|---|---|
| `e223ac4` | Add TradeCandidate lineage and agent attribution to the backtest engine |
| `3b25be7` | Phase 1 BTC/ETH quantitative failure analysis |
| `50b7b8f` | Phase 3 exact asset/timeframe/model evidence binding |
| `4181e08` | Phase 4 dynamic trading universe selection, plus lint cleanup |
| `284adcc` | style: fix line length in test_candidate_lineage.py |

## Files changed

33 files changed, +10,289 / -134 lines versus the source branch. Breakdown by area:

- **New package `packages/candidates/`** (models.py, builder.py) — TradeCandidate entity and
  pure builder.
- **New package `packages/evidence/`** (models.py, store.py, builder.py) — exact-match
  evidence key/record/store.
- **New package `packages/universe/`** (models.py, selector.py, live_source.py,
  build_snapshot.py) — dynamic universe eligibility.
- **New module `packages/research/failure_analysis.py`** — BTC/ETH failure classification.
- **Modified `packages/backtest/engine.py`** — wires candidate capture into the replay loop;
  `get_candidates(session_id)` accessor added.
- **Modified `packages/backtest/models.py`** — added `BacktestConfig.fold_number` (lineage
  metadata only, no behavior change).
- **Modified `packages/backtest/metrics.py`** — `zip(..., strict=False)` lint fix only, no
  behavior change (Sharpe/Sortino/Calmar logic unchanged from the prior checkpoint).
- **Modified `packages/research/campaign.py`** — captures `engine.get_candidates()` per
  experiment, writes `CANDIDATES.csv`, sets `session_name`/`fold_number` on `BacktestConfig` so
  candidates carry correct lineage identity.
- **Modified `packages/research/gate.py`** — added `GATE_VERSION` constant for evidence
  binding; lint fix for the mutable-default argument.
- **New docs**: `BTC_ETH_FAILURE_ANALYSIS.md`, `ASSET_SPECIFIC_EVIDENCE_POLICY.md`,
  `UNIVERSE_SELECTION_POLICY.md`.
- **New/updated data artifacts** in `docs/research/experiments/`: `CANDIDATES.csv` (8,198
  rows), `FAILURE_ANALYSIS.csv` (30 rows), `EVIDENCE_RECORDS.csv` (30 rows),
  `UNIVERSE_SNAPSHOT.json`, and re-generated `EXPERIMENT_LEDGER.csv` / `GATE_RESULTS.csv` /
  `CAMPAIGN_MANIFEST.json` (byte-identical `GATE_RESULTS.csv` to the prior checkpoint —
  confirms the candidate-capture instrumentation changed nothing about trading behavior).
- **New tests**: `test_candidate_lineage.py` (2), `test_evidence_exact_match.py` (9),
  `test_universe_selector.py` (15) — 26 new tests, all offline/deterministic.

## Tests run

Command: `python -m pytest tests/ -q` (Python 3.12.3, project venv, `pip install -e ".[dev]"`).

**Result: PASSED (with 3 pre-existing, environment-caused failures — see below)**

```
3 failed, 186 passed, 12 skipped, 2 warnings in ~3s
```

- **Passed: 186** (160 baseline + 26 new this checkpoint). Every backtest, candidate-lineage,
  evidence, and universe test in this checkpoint's scope passed, including a regression test
  pinned to the real campaign's actual numbers (0 `UNIVERSAL_APPROVED`, 14
  `ASSET_SPECIFIC_APPROVED`, all BTC/USDT).
- **Failed: 3, all pre-existing and unrelated to this checkpoint's changes** (present before
  this branch existed, confirmed by re-running the identical suite against
  `claude/full-alpha-research-campaign-joszu3`):
  - `test_binance_public_adapter.py::test_binance_public_fetch_candles` — **BLOCKED**:
    `api.binance.com` returns HTTP 451 (geo-restricted) from this sandbox network. Unrelated
    to `data-api.binance.vision`, which this checkpoint's new code (like the prior one) uses
    successfully.
  - `test_binance_public_adapter.py::test_binance_public_fetch_order_book_snapshot` —
    **BLOCKED**, same cause.
  - `test_db_migration.py::test_alembic_migration_lifecycle` — **BLOCKED**: `infra/
    migrations/alembic.ini` path resolution issue in this sandbox's working directory; no
    PostgreSQL/Alembic environment provisioned here.
- **Skipped: 12**, all `test_paper_durable_persistence.py` — **NOT AVAILABLE**: require
  `PAPER_DB_TEST_URL` (a disposable PostgreSQL instance), not provisioned in this sandbox.
  Explicitly skip-guarded in the test file itself, not silently ignored.

`ruff check .` (full repo): **PASSED** — zero findings, including this checkpoint's new files.

`mypy packages apps` (project's `strict = True` config): **FAILED, pre-existing** — 47 errors
in `packages/agents`, `packages/risk`, `packages/positions`, `packages/features` alone (none
of which this checkpoint touched), confirmed present on the source branch before this work
started. This checkpoint's new modules (`candidates`, `evidence`, `universe`,
`research/campaign.py`) add further strict-mode gaps of the same kind already pervasive in the
codebase (missing `Dict`/`List` generic type arguments, a few missing return-type
annotations) — not remediated here; see "Remaining gaps."

The live, opt-in, network-touching entrypoints (`python -m packages.research.data_fetcher`,
`python -m packages.research.campaign`, `python -m packages.universe.build_snapshot`,
`python -m packages.evidence.builder`, `python -m packages.research.failure_analysis`) were
each run for real at least once during this checkpoint to produce the actual committed
artifacts — **PASSED** (real output, not fabricated), logged inline in this conversation.
Campaign V2 (multi-symbol, per the plan's Phase 13) was explicitly **NOT RUN** — out of scope
for Checkpoint 1 per the instruction to stop here.

## Design decisions

1. **Candidate lineage lives inside the existing backtest engine loop, not a parallel
   pipeline.** `EventDrivenBacktestEngine._run_backtest_async` now builds a `TradeCandidate` at
   the same point it already builds the `TradeIntent`/risk decision/fill, and finalizes it at
   the same point it already finalizes the `TradeEpisode`. This guarantees the lineage can
   never drift from the actual trade record — `test_candidate_lineage.py` asserts
   `len(closed_candidates) == report.trade_count` as an equality invariant, not an
   approximation.
2. **Agent attribution convention is explicit and documented, not implied.**
   `agent_source` = the accepted, direction-agreeing signal with the highest critic-adjusted
   confidence (deterministic tie-break by `agent_id`). This is stated as a convention in
   `packages/candidates/models.py`'s docstring because the underlying system is a genuine
   multi-agent consensus, not a single-agent-per-trade system — attribution is a real modeling
   choice, not a discoverable fact, and hiding that would misrepresent the mechanism.
3. **Evidence binding uses a plain `NamedTuple` key with tuple equality**, deliberately not a
   dict/dataclass with a custom `__eq__` or any similarity scoring — this was the most direct
   way to make "no fallback" structurally true rather than a policy that could regress. Backed
   by 9 tests exercising each individual field's mismatch case.
4. **Walk-forward evidence binds to a combined dataset checksum** (`compute_evidence_dataset_
   checksum`, SHA-256 over the sorted 3 per-fold checksums), because each OOS fold in this
   campaign design runs against its own sliced dataset — there is no single contiguous dataset
   to bind to, and inventing one would misrepresent what was actually tested.
5. **Universe selection is split into a pure selector and a single live-fetch module**
   specifically so the default test suite never needs network access — matching the explicit
   instruction that default tests must stay offline. `live_source.py` and
   `build_snapshot.py` are the only two files in the whole checkpoint that make live calls, and
   neither is imported by anything that runs automatically.
6. **`model_version = "n/a"` is an explicit, participating value in the evidence key**, not a
   wildcard or omitted field — Checkpoint 1 has no trained ML model (Phase 7 is later), and
   representing that as a real string value (rather than leaving the field out of the schema)
   keeps the exact-match guarantee uniform across every field.

## Discovered risks

1. **`ExitProtector`'s trailing stop appears to dominate exits completely.** 1,090 of 1,090 OOS
   closed trades across the whole campaign exited via `TRAILING_STOP` — zero via
   `INITIAL_STOP` or `TAKE_PROFIT`. This means the take-profit target is, empirically, never
   reached before the trailing stop catches the trade, on both symbols, across all 15 configs.
   Not fixed in this checkpoint (out of scope — flagged for design review before Phase 6+
   regime-aware routing is built on top of the current exit model).
2. **The strategy grid's edge does not transfer across symbols.** This is the headline finding
   of `BTC_ETH_FAILURE_ANALYSIS.md`: `trend_agent_v1` is the dominant trade source on both
   BTC/USDT (positive expectancy) and ETH/USDT (negative expectancy) under identical rules. Any
   Phase 13 multi-asset campaign that reuses this same rule-based grid unmodified against new
   symbols (BNB, SOL, etc.) should be expected, on current evidence, to fail the same way
   unless the agents or their parameters are made asset-aware.
3. **Mypy strict-mode debt is large and pre-existing** (47 errors before this checkpoint, more
   added by this checkpoint's new code following the same untyped patterns already common in
   the codebase). Not a functional risk today (ruff and the full test suite are clean), but it
   will compound as more research/candidate/evidence code is added in later phases and should
   be addressed before, not after, Phase 7's ML code lands.
4. **`docs/research/experiments/CANDIDATES.csv` is a committed 4.4MB file** that will grow with
   every future campaign run (each re-run currently overwrites it, but a future design that
   appends across campaigns, or Campaign V2's larger multi-symbol/multi-timeframe scope, could
   make this unwieldy in git). Worth deciding a retention/archival policy before Phase 13.
5. **Universe eligibility is a point-in-time snapshot with no automatic staleness
   enforcement.** `UniverseSnapshot.generated_at` is recorded but nothing currently rejects an
   old snapshot automatically — flagged in `UNIVERSE_SELECTION_POLICY.md` as a Phase 19 concern.

## Remaining gaps (explicitly out of scope for Checkpoint 1, per instruction to stop here)

- No 1h/4h datasets downloaded; Checkpoint 1 stayed on the existing 1D BTC/ETH data used by the
  original campaign.
- No ML meta-label model trained (Phase 7/8) — `model_type`/`model_version` in the evidence
  schema are real fields ready to receive one, but nothing populates them yet beyond the
  `"n/a"` rule-based placeholder.
- No Campaign V2 (multi-symbol beyond BTC/ETH, multi-timeframe) run.
- No LLM market agents (Phase 16), no shadow mode (Phase 18), no continuous monitoring (Phase
  19) — none attempted.
- Live trading remains disabled; nothing in this checkpoint touches
  `LIVE_TRADING_ENABLED` or any private exchange API.
- Mypy strict-mode gaps in the new modules not remediated (see risk #3).

## Recommended next checkpoint

Given risk #2 (the BTC-specific edge doesn't transfer) and risk #1 (universal trailing-stop
dominance), the highest-value next step is **not** immediately widening to more symbols with
the same unmodified rule grid — that would very likely just reproduce Checkpoint 1's ETH
result across BNB/SOL/XRP/ADA/DOGE. Recommend, in order:

1. A short, focused review of `ExitProtector`'s trailing-stop vs. take-profit interaction
   (risk #1) before building anything else on top of the current exit model.
2. Begin Phase 6 (regime detection / strategy router) scoped narrowly to BTC/ETH first, using
   the regime breakdown already computed in `BTC_ETH_FAILURE_ANALYSIS.md` §4 as a starting
   point, rather than jumping straight to Phase 13's multi-symbol campaign.
3. Only after that, extend to the 7 eligible universe symbols
   (`UNIVERSE_SNAPSHOT.json`) with Phase 5 (1h/4h data) and Phase 13 (Campaign V2) — by which
   point there should be a defensible hypothesis for *why* a config would generalize, not just
   a hope that it will.
