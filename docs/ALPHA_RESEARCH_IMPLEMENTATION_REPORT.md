# ALPHA RESEARCH — IMPLEMENTATION REPORT

**Date:** 2026-07-23 · **Scope:** quantitative research pipeline (dataset → features →
labels → splits → baselines → training → calibration → walk-forward evaluation →
strategy evidence → runtime integration) for the AI Trading Advisor.

---

## 1. Git

| | |
|---|---|
| Branch | `feat/alpha-dataset-training` |
| Base branch | `feat/ai-trading-advisor` (NOT `main` — `main` predates the paper-runtime remediation and Advisor dependencies) |
| Commits | 9 (`b5eb86e` … `01ddc90`), one per phase, each with tests passing before the next started |
| Working tree | Clean at time of writing |

```
01ddc90 docs: add alpha research and validation runbooks
90d1e87 test: add end-to-end alpha research pipeline coverage
3223fd8 feat: integrate approved models with recommendation runtime
39b5093 feat: publish strategy evidence and approval gates
dfc9f10 feat: add calibration and walk-forward evaluation
f173d68 feat: add baseline evaluation and logistic regression training
4dc486e feat: add chronological splits with purge and embargo
7dabf30 feat: add point-in-time features and cost-aware labels
b5eb86e feat: add reproducible market dataset pipeline
```

## 2. Architecture — new package

```
packages/research/
├── config.py             ResearchConfig + sub-configs, YAML-loadable, config_hash
├── checksums.py           thin wrappers over EXISTING backtest checksum scheme
├── candle_repository.py   wraps EXISTING HistoricalCandleIngestionService
├── dataset_builder.py     validates raw candles -> RawCandleDataset artifact
├── feature_dataset.py     point-in-time walk over the EXISTING FeaturePipeline
├── labels.py               cost-aware triple-barrier labels (uses EXISTING cost_estimator)
├── splits.py               wraps EXISTING walk_forward_runner; purge/embargo
├── baselines.py            calls REAL agents / DecisionService, not re-implementations
├── training.py             scikit-learn -> EXISTING LogisticRegressionWeights format
├── calibration.py          Platt/isotonic, reuses EXISTING prediction.calibration metrics
├── evaluation.py           trade + classification metrics, breakdowns, calibration
├── overfitting.py          ExperimentTracker, Deflated Sharpe Ratio, PBO (CSCV)
├── evidence_publisher.py   ONLY writer to the EXISTING evidence_registry
├── runtime_loader.py       ONLY path into the EXISTING model_registry; requires APPROVED
├── artifacts.py            file-based dataset/model/evaluation/evidence store
└── cli.py                  7 argparse subcommands, no side effects on import
```

Every module above explicitly reuses something that already existed before this phase
(`packages.backtest.datasets`, `packages.backtest.walk_forward`,
`packages.market_data.ingestion.historical`, `packages.market_data.guardian`,
`packages.features.pipeline`, `packages.governance.cost_estimator`,
`packages.governance.decision_service`, `packages.agents.*`,
`packages.prediction.{direction_model,return_model,calibration,evaluation}`,
`packages.recommendation.evidence_service`, `packages.recommendation.timeframes`) — no
second, incompatible feature/decision/cost pipeline was created.

No components from `packages/recommendation`, `packages/prediction`, `packages/chat_agent`,
or `packages/backtest` were redesigned or replaced. `packages/market_data/adapters/
binance.py`'s pre-existing `is_closed=True`-on-every-kline behavior was worked around
defensively in `dataset_builder.py` (same pattern already used in
`packages/recommendation/service.py`), not "fixed" at the source — consistent with the
prior phase's decision to leave shared adapters alone.

## 3. Data

| | |
|---|---|
| Source | Binance public Spot REST (`BinancePublicMarketDataProvider`), no API key |
| Symbols exercised in this phase's real run | `BTCUSDT` |
| Timeframe | `1h` |
| Date range (real run) | 2026-06-01 → 2026-07-20 (~7 weeks) |
| Candle count | 1177 |
| Duplicate candles | 0 |
| Rejected candles | 0 |
| Dataset quality status | `VALIDATED` |
| Dataset checksum | `0df430e136b589ee...` (SHA-256, same scheme as `packages.backtest.datasets`) |
| Dataset ID | `8ec92cbf-f40e-49aa-ba6d-23fd23b68612` |

`ETHUSDT` and the `15m`/`4h` timeframes (part of the Version 1 scope per
`configs/research/btc_eth_v1.yaml`) were **not** pulled in this phase's real run — only
`BTCUSDT`/`1h` was exercised, as a single bounded smoke test (see §9). The full
multi-symbol, multi-timeframe download was not executed; running it is described in
`docs/ALPHA_RESEARCH_RUNBOOK.md` §6 and is real, separate work.

## 4. Features and labels

- **Feature version:** `standard_v1` (13 features: returns, EMA slope, ADX, RSI, ATR,
  volatility, relative volume, z-score, Bollinger position, Donchian breakout — the exact
  set `packages.prediction.feature_adapter.FEATURE_NAMES` already defines).
- **Label version:** `triple_barrier_v1`.
- **Point-in-time guarantee:** two independent layers (candle-history slicing in
  `feature_dataset.py`, plus `FeaturePipeline`'s own `close_time <= as_of_time` filter);
  verified by a leakage test that rebuilds the feature table with and without future
  candles present and asserts every shared row is byte-identical.
- **Cost assumptions:** the EXISTING `packages.governance.cost_estimator` (fee 10bps +
  spread 2bps BTC/4bps other + slippage 5bps + uncertainty buffer 5bps ≈ 22bps
  round-trip for BTCUSDT) — the same numbers the live paper-trading path uses.

Real run (BTCUSDT/1h smoke dataset): 268 rows after point-in-time feature+label join and
chronological split for `horizon_minutes=60`.

## 5. Models

| | |
|---|---|
| Model actually trained | Logistic Regression (`packages.research.training.train_logistic_direction_weights` + `train_linear_return_weights`) |
| Model version | `logreg_smoke_v1` |
| Model ID | `9a1c08ec-a941-46da-a309-a08ff7217ee6` |
| Hyperparameters | `{"C": 1.0, "max_iter": 1000}`, `random_seed=42` |
| Train rows | 268 |
| Artifact checksum | `4cc9b203fd925b0d...` |
| Artifact format | plain JSON (`LogisticRegressionWeights`/`LinearRegressionWeights`) — **no pickle/joblib anywhere in this pipeline** |
| XGBoost/LightGBM | **Not implemented** — a deliberate scope decision (plan explicitly permits this: "only if dependency and environment support are clean... do not add both merely for breadth"), documented in `docs/ALPHA_MODEL_TRAINING.md` §2 |

## 6. Evaluation (real BTCUSDT/1h smoke run, `num_folds=2`, `horizon_minutes=60`)

| Subject | Trades (test split) | Net PnL (bps) |
|---|---:|---:|
| `NO_TRADE` | 0 | — |
| `BUY_AND_HOLD` | 188 | −4559.48 |
| `TREND_ONLY` (real `TrendAgent`) | 36 | −965.50 |
| `MEAN_REVERSION_ONLY` (real `MeanReversionAgent`) | 6 | −189.49 |
| `BREAKOUT_ONLY` (real `BreakoutAgent`) | 6 | −194.01 |
| `MULTI_AGENT_NO_ML` (real `DecisionService`) | 39 | −1028.75 |
| `logreg_smoke_v1` (trained model) | 0 | — |

**Every baseline lost money net of real fees/spread/slippage over this specific 7-week
window.** The trained model made zero test-split decisions (its predicted probabilities
never cleared the 0.58 decision threshold, `packages.recommendation.config
.recommendation_config.min_probability_profit`, in this small/undertrained run).

**These numbers describe one specific 7-week BTCUSDT window and must not be read as a
general statement about any of these strategies' viability.** The sample is far too small
and too short to support any such claim, and this report makes none.

Calibration: not computed for `logreg_smoke_v1` (zero test-split predictions to
calibrate against — correctly reported as `None`, never fabricated).

## 7. Evidence

| | |
|---|---|
| Evidence published for | `MULTI_AGENT_NO_ML` evaluation, registered as strategy `multi_agent_consensus_pipeline` v`smoke_test_1.0.0` |
| Status | **`REJECTED`** |
| Reasons | `INSUFFICIENT_OOS_TRADE_COUNT`, `INSUFFICIENT_WALK_FORWARD_WINDOWS`, `PROFIT_FACTOR_BELOW_THRESHOLD`, `SHARPE_BELOW_THRESHOLD`, `NON_POSITIVE_EXPECTANCY` |

This is the **correct, expected** outcome for a 7-week, 2-fold smoke sample evaluated
against production-scale default gates (≥100 OOS trades, ≥3 walk-forward folds, profit
factor ≥1.20, Sharpe ≥1.00, positive expectancy) — not a defect in the pipeline. No gate
was loosened to make this — or any other — result look better. A rejected strategy is
recorded here as a complete, valid research result, per the plan's explicit instruction.

## 8. Runtime integration

- `packages.research.runtime_loader.load_approved_model` refuses to load anything unless
  the corresponding `StrategyEvidence` status is `APPROVED` — proven by
  `test_load_approved_model_refuses_when_no_evidence` /
  `test_load_approved_model_refuses_when_evidence_not_approved`, and confirmed again in
  this phase's real run: since the smoke evidence was `REJECTED`, no model was (or could
  be) loaded into `packages.prediction.registry.model_registry`.
- `test_recommendation_service_gated_by_default_and_approved_registries` proves BOTH
  directions with the same `RecommendationService` code path: with the real, shipped-empty
  registries it never reaches `PROPOSALS_AVAILABLE`; with a real `APPROVED` evidence
  record and a model loaded through `load_approved_model`, the exact same service
  produces a real, traceable proposal (`evidence_id` populated).
- **`NO_TRADE` still works** — it is the trivial baseline and is exercised directly in
  every walk-forward evaluation run (see §6 table).
- The repository's shipped state (no committed artifacts) is unaffected by this phase:
  `artifacts/` and `data/research/` are gitignored, and the smoke run's local artifacts
  were deleted after the run. `packages.prediction.registry.model_registry` and
  `packages.recommendation.evidence_service.evidence_registry` remain empty by default —
  `RecommendationService` still resolves to `INSUFFICIENT_EVIDENCE`/`STRATEGY_NOT_APPROVED`
  in production, exactly as before this phase.

## 9. Verification

| Check | Command | Result |
|---|---|---|
| Linter | `ruff check .` | **PASSED** (0 errors, full repo) |
| Unit tests (full repo) | `pytest tests/unit -q` | **PASSED** 355/355 |
| Unit tests (alpha research only) | `pytest tests/unit -k research -q` | **PASSED** 112/112 |
| Type checker | `mypy packages/research` | **PARTIAL** — real `Optional`-narrowing and missing-annotation issues found in new code were fixed; 11 findings remain: `runtime_loader.py`'s two `DirectionModel`/`ReturnModel` Protocol-settability mismatches are pre-existing design from the prior (AI Trading Advisor) phase, not touched here; the rest are a repo-wide missing `pydantic.mypy` plugin config (same root cause noted in the prior phase's report) or numpy/pandas `Any`-return noise |
| Integration tests (`tests/integration`) | — | **NOT AVAILABLE** — pre-existing tests in that suite require a live Postgres instance not available in this environment, unrelated to this phase (documented in `docs/review/COMMAND_EVIDENCE.md` before this phase started) |
| Artifact checksum tests | `pytest tests/unit/test_research_dataset.py -k checksum` | **PASSED** — `ArtifactStore.verify_dataframe_checksum` round-trip and mismatch-detection both covered |
| CLI smoke tests (offline) | `pytest tests/unit/test_research_cli.py -q` | **PASSED** 5/5 (parser wiring, `--dry-run` side-effect-free, `list-models`/`list-evidence`) |
| CLI smoke test (real Binance data) | manual, see §6/§7 and `docs/ALPHA_RESEARCH_RUNBOOK.md` §3 | **RAN** — full `download-data → build-dataset → train-model → run-walk-forward → publish-evidence` sequence executed successfully against live data |
| Bounded real-data research experiment | see §3, §6, §7 | **RAN AT SMOKE SCALE ONLY** — a single symbol/timeframe, ~7 weeks; evidence correctly `REJECTED`, not approved |
| Formatter | ruff includes formatting-adjacent lint rules (`I001` import order etc.); no separate `black`/`ruff format` invocation configured in this repo | **N/A** — no distinct formatter step exists in this repo's tooling beyond `ruff check` |

Two real bugs were found and fixed via this manual real-data run (not from static
review):

1. `CandleRepository.__init__` created the cache directory as a side effect even during
   `download-data --dry-run` (its constructor unconditionally calls `mkdir`). Fixed:
   dry-run mode no longer constructs a `CandleRepository` at all.
2. `ArtifactStore.list_ids("models")` also returned the `*_direction.weights`/
   `*_return.weights` artifact filenames alongside real model IDs, because both end in
   `.json`. Fixed: `list_ids` now excludes `*.weights.json`.

## 10. Remaining gaps — not hidden

- **Insufficient data.** Only one symbol, one timeframe, ~7 weeks was actually pulled and
  evaluated with real data. The Version 1 scope (`BTCUSDT`+`ETHUSDT`, `15m`/`1h`/`4h`,
  multi-year history) was not executed. `docs/ALPHA_RESEARCH_RUNBOOK.md` §6 describes what
  running it would take (materially longer, bounded by Binance rate limits and the
  per-entry real-agent evaluation cost in `baselines.py`).
- **No strategy is approved.** Every baseline lost money in the one real window tested;
  the trained model made no test-split decisions at all. This is an honest, correctly
  computed result from a too-small sample — not evidence for or against the strategies at
  a meaningful scale.
- **Weak/undertrained model.** `logreg_smoke_v1` was trained on 268 rows and produced zero
  test-split trades — nowhere near enough data to expect a useful classifier. Calibration
  could not be computed as a direct consequence.
- **Overfitting risk is present but unmeasured at scale.** `ExperimentTracker`/DSR/PBO are
  implemented and tested (`packages/research/overfitting.py`), but only one model
  configuration was actually trained in this phase's real run — the multiple-testing
  machinery has nothing yet to meaningfully warn about. If several hyperparameter/
  feature-set variants are tried in a future run, use `ExperimentTracker` from the start
  so `experiments_tried` (and DSR/PBO) reflect the true trial count.
- **No durable shadow-outcome storage.** Not part of this phase's scope (the prior AI
  Trading Advisor phase's `docs/AI_TRADING_ADVISOR_ARCHITECTURE.md` §6 already documents
  this as an open gap); this phase did not add it either.
- **Unverified infrastructure:** integration tests requiring Postgres were not run (no
  disposable Postgres instance available in this environment); the `tests/integration`
  suite's status is unchanged from before this phase.
- **mypy is not fully clean** on `packages/research` — see §9 for the itemized remaining
  findings and why each was left as-is.
- **Gap detection in `dataset_builder.py` is informational only** — a dataset with
  material gaps still builds (`DEGRADED`, not blocked). Downstream feature/label quality
  in gappy regions is not separately flagged.

## 11. Final decision

```
B — RESEARCH PIPELINE READY, STRATEGY NOT YET APPROVED
```

The pipeline is real, complete, and tested end-to-end: reproducible checksummed datasets,
verified point-in-time features, cost-aware labels with a proven no-leakage boundary,
purge/embargo-correct chronological and walk-forward splits, six real (not
re-implemented) comparison baselines, a trained model that loads directly into the
existing runtime inference contracts, real calibration and walk-forward evaluation
metrics, a two-layer evidence-approval policy that never loosens its gates, and a
one-way, evidence-gated path into the runtime prediction registry — all proven against
both offline fixtures (355 passing tests) and a real, bounded live-data run.

No strategy has cleared the approval bar yet, because no adequately-sized real-data run
has been executed — that is real, separate, and substantially more time-consuming work
(§10), not a defect in what was built this phase. This report does not claim otherwise,
and the pipeline itself — via its own gates — refused to claim otherwise when it was
tested against real data.
