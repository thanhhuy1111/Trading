# Crypto Multi-Agent Trading Advisor — Progress

## Current state

- Branch: `main`
- Current phase: Phase 15 — Research & Thesis Package
- Last completed task: Phase 14 — Advanced Expansion
- Next task: Phase 15 — Research & Thesis Package
- Full campaign through Phase 15 is authorized by `CODEX_FULL_CAMPAIGN_EXECUTOR.md`; phases
  remain sequential and safety-gated.

## Completed before campaign docs

Theo playbook, Git và `docs/MULTI_AGENT_ADVISOR_PROGRESS.md`:

- Step 1 — codebase architecture normalization.
- Step 2 — public futures/derivatives data.
- Step 3 — derivatives feature pipeline.

Các campaign docs sau không tồn tại ở đầu Phase 4A và được tạo từ playbook thay vì bịa lịch sử:

- `docs/campaign/CRYPTO_MULTI_AGENT_SYSTEM_PLAN.md`
- `docs/campaign/PROGRESS.md`
- `docs/campaign/QUALITY_BASELINE.md`
- `docs/campaign/tasks/PHASE_04_XGBOOST.md`

`AGENTS.md` cũng không tồn tại trong repo tại thời điểm khảo sát.

## Phase 4A — Research & Design

Status: **COMPLETE**

### Files changed

- `docs/campaign/CRYPTO_MULTI_AGENT_SYSTEM_PLAN.md`
- `docs/campaign/QUALITY_BASELINE.md`
- `docs/campaign/tasks/PHASE_04_XGBOOST.md`
- `docs/campaign/PROGRESS.md`

Không sửa production code.

### Architecture decisions

- Exact scope: `BTCUSDT`, `4h`, horizon 1 bar, classes
  `BEARISH/NEUTRAL/BULLISH`.
- Label theo future simple return và trailing 20-bar volatility band; `k` chỉ chọn từ train.
- Hai dataset mode độc lập: `price_only` và `price_plus_derivatives`; không impute/fallback.
- Exact registered mapping `BTCUSDT -> BTC/USDT`, rồi validate từng source record.
- Validate riêng spot venue `binance` và derivatives venue `binance_usdm_futures`.
- Point-in-time backward join dùng field-level `available_at`, explicit lineage và target luôn
  sau as-of; basis bị loại đến khi có two-source timestamp lineage.
- Historical candle availability dùng deterministic close-publication contract; ingestion
  time chỉ là audit metadata, không làm checksum drift.
- Derivatives dùng fixed 5m cadence/tolerance; sparse/bursty history bị reject.
- Ba expanding folds với one-bar purge; không reuse independent-segment splitter nguyên trạng.
- Bốn comparators: majority, seeded random, Logistic Regression và XGBoost.
- Validation-only temperature calibration; confidence chỉ từ calibrated probability.
- Final base model/calibration dùng disjoint chronological 0–90%/90–100% windows và không
  refit base model sau calibration.
- Approval fail-closed theo từng fold qua dedicated approval service; artifact yếu, forged hay
  direct-injected phải `REJECTED`.
- Native XGBoost JSON trong gitignored `data/`; runtime read-only chỉ load exact `APPROVED`.

### Independent safety review

Read-only reviewer đã audit lookahead, mode split, symbol/cache alias, approval bypass,
confidence calibration, derivatives cadence, baseline probability semantics và acceptance
criteria. Tất cả findings được đưa vào phase contract/test matrix; final re-review không còn
finding HIGH/MEDIUM. Reviewer không sửa file.

### Verification

- Targeted:
  `.venv/bin/pytest tests/unit/test_price_projection_training.py
  tests/unit/test_retraining_workflow.py tests/unit/test_retraining_calibration.py
  tests/unit/test_derivatives_pipeline.py tests/unit/test_derivatives_history.py
  tests/unit/test_registries.py tests/unit/test_lookahead_leakage.py -q`
  → 40 passed.
- Full pytest: `.venv/bin/pytest tests/ -q`
  → 489 passed, 12 skipped, 1 failed.
- Full failure:
  `tests/integration/test_db_migration.py::test_alembic_migration_lifecycle`
  → thiếu `infra/migrations/alembic.ini`, đúng known Alembic baseline issue.
- Ruff: `.venv/bin/ruff check .` → clean.
- Mypy: `.venv/bin/mypy packages/ apps/`
  → 180 errors in 67 files, không tăng baseline.
- Runtime safety values:
  `LIVE_TRADING_ENABLED=False`,
  `PRIVATE_EXCHANGE_API_ENABLED=False`,
  `FEATURE_FLAGS_LIVE_TRADING=False`.
- `git diff --check` → clean.

### Known issues

- Baseline bàn giao: 487 passed, 3 failed; Ruff clean; 180 mypy errors.
- Root `.venv` không tồn tại lúc bắt đầu; Phase 4A đã tạo local gitignored `.venv`
  Python 3.12.12 từ `.[dev,research]` để verify.
- XGBoost 3.3.0 đã được cài trong `.venv`; research dependency được bound
  `xgboost>=3.2.0,<4.0.0`.
- Derivatives history không backfill tùy ý và chỉ giữ 30 ngày.

## Phase 4B — Dataset & Labels

Status: **COMPLETE**

### Files changed

- `packages/common/immutable.py`
- `packages/market_data/derivatives_models.py`
- `packages/market_data/adapters/binance_futures.py`
- `packages/features/calculators/derivatives.py`
- `packages/retraining/xgboost_contracts.py`
- `packages/retraining/xgboost_dataset.py`
- `tests/unit/test_binance_futures_adapter.py`
- `tests/unit/test_xgboost_dataset.py`
- campaign progress/quality/task docs.

### Delivered

- Deeply immutable, Pydantic-serializable dataset/label/lineage/report contracts with
  deterministic schema hash, sample IDs and dataset checksum.
- Two strict modes (`price_only`, `price_plus_derivatives`) with no fallback or imputation.
- Exact `BTCUSDT -> BTC/USDT`, Binance spot/futures venue and H4 closed-candle validation.
- Deterministic candle availability (`close_time + 1ms`); ingestion clocks are audit-only and
  excluded from checksums.
- Field-level derivatives `event_time`, `available_at` and contributing source timestamps;
  legacy, delayed, stale, unhealthy, wrong-source and irregular 5m histories fail closed.
- Metric-specific derivative calculator ordering, so unrelated snapshot timestamps cannot
  reorder funding/open-interest series.
- Strict one-bar volatility-band labels, fixed candidate-k distribution report, exact feature
  schema and nested aggregate/report validation.
- Basis feature remains excluded because two-source point-in-time lineage is unavailable.

### Independent safety review

Read-only review initially found deep-mutation, nested-lineage, malformed-candle, calculator
time-axis, rejected-report and aggregate-integrity gaps. All CRITICAL/HIGH/MEDIUM findings
were addressed with regression tests; the final review reported none remaining. Reviewer did
not edit files.

### Verification

- Targeted:
  `.venv/bin/pytest tests/unit/test_binance_futures_adapter.py
  tests/unit/test_derivatives_history.py tests/unit/test_derivatives_calculators.py
  tests/unit/test_derivatives_pipeline.py tests/unit/test_xgboost_dataset.py -q`
  → 55 passed.
- Full pytest: `.venv/bin/pytest tests/ -q`
  → 512 passed, 12 skipped, 1 failed.
- Full failure remains
  `tests/integration/test_db_migration.py::test_alembic_migration_lifecycle`
  because `infra/migrations/alembic.ini` is absent; this is the known baseline issue.
- Ruff: `.venv/bin/ruff check .` → clean.
- Mypy: `.venv/bin/mypy packages/ apps/` → 180 errors in 67 files, unchanged baseline.
- `git diff --check` → clean.
- Runtime safety values remain:
  `LIVE_TRADING_ENABLED=False`,
  `PRIVATE_EXCHANGE_API_ENABLED=False`,
  `FEATURE_FLAGS_LIVE_TRADING=False`.

### Scope confirmation

No trainer, model artifact, approval service, runtime serving, private exchange API, live
trading flag, order path or fabricated market/research result was added.

## Phase 4C — Training & Walk-forward

Status: **COMPLETE**

### Files changed

- `pyproject.toml`
- `packages/retraining/xgboost_training.py`
- `tests/unit/test_xgboost_training.py`
- campaign progress/quality/task docs.

### Research and dependency decision

- XGBoost official package metadata hiện yêu cầu Python `>=3.12` và có wheel macOS ARM;
  `.venv` cài thực tế `xgboost==3.3.0`.
- Research dependency được bound `xgboost>=3.2.0,<4.0.0`.
- Native `.json` model IO vẫn là format cho Phase 4D; Phase 4C không ghi artifact.
- Official references:
  [XGBoost package](https://pypi.org/project/xgboost/),
  [XGBoost model IO](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html).

### Delivered

- Ba expanding walk-forward folds theo unique timestamp groups, one-bar purge và
  `max(target_time) < next as_of_time`.
- Train-only candidate-`k` selection, empirical-prior majority/seeded-random baselines,
  train-only StandardScaler/Logistic và fixed deterministic CPU XGBoost.
- Validation-only scalar temperature calibration; missing-class, constant/uniform logits,
  invalid probabilities và third-party failures đều fail closed bằng machine reason codes.
- Per-fold và aggregate accuracy, balanced accuracy, macro F1, MCC, log loss, multiclass
  Brier, 10-bin ECE/reliability counts và 3x3 confusion matrix.
- Full labels/probabilities, candidate distributions, partition checksums, calibration
  evidence và mọi rejected fold được giữ trong report.
- Final base fit trên purged prefix 0–90%; calibration chỉ trên disjoint trailing 90–100%;
  model fit đúng một lần và không refit sau calibration.

Synthetic fixtures chỉ kiểm contract/determinism/failure handling; không được diễn giải là
evidence về hiệu quả trên thị trường thật và không tạo trạng thái approved.

### Independent safety review

Read-only reviewer phát hiện calibration degenerate vẫn được chấp nhận và free-form
third-party exceptions lọt vào reason codes. Hai finding đã được sửa bằng
`CALIBRATION_DEGENERATE` và stable fit/prediction reason codes. Final review không còn
CRITICAL/HIGH/MEDIUM; reviewer không sửa file.

### Verification

- `.venv/bin/pytest tests/unit/test_xgboost_training.py -q` → 15 passed.
- `.venv/bin/pytest tests/ -q` → 527 passed, 12 skipped, 1 failed.
- Failure duy nhất vẫn là known baseline
  `tests/integration/test_db_migration.py::test_alembic_migration_lifecycle` do thiếu
  `infra/migrations/alembic.ini`.
- `.venv/bin/ruff check .` → clean.
- `.venv/bin/mypy packages/ apps/` → 180 errors in 67 files, unchanged baseline; không có
  lỗi mới trong `xgboost_training.py`.
- Safety flags vẫn `False/False/False`; `git diff --check` clean.

### Scope confirmation

Không tạo artifact, approval registry/service, runtime serving, private API, live trading,
order path hoặc kết quả hiệu quả nghiên cứu giả.

## Phase 4D — Approval & Artifact

Status: **COMPLETE**

### Files changed

- `packages/registries/models.py`
- `packages/registries/registry.py`
- `packages/retraining/xgboost_approval.py`
- `packages/retraining/xgboost_artifacts.py`
- `tests/unit/test_registries.py`
- `tests/unit/test_xgboost_approval.py`
- campaign progress/quality/task docs.

### Delivered

- Dedicated approval service recomputes the complete deterministic Phase 4C training report
  from the immutable dataset and compares that evidence exactly before any approval.
- Caller model is bound to the recomputed model through native XGBoost JSON bytes; publication
  writes only the trusted recomputed model, never the caller-supplied object.
- Every fold is independently re-audited for partition checksums, train-only threshold,
  labels, validation-only calibration, comparator semantics, probabilities, metrics and all
  strict performance gates.
- Registry insertion is append-only and entries are deeply immutable, so duplicate overwrite,
  alias mutation and rejected resurrection are blocked. Registry status alone is still not a
  trusted approval: Phase 4E must require the private service receipt too.
- Exactly five files are atomically published: `model.json`, `metadata.json`,
  `feature_schema.json`, `evaluation.json`, `approval.json`. Native JSON is round-tripped over
  the complete dataset and all four approval inputs are SHA-256 checksummed.
- Artifact payloads use strict, extra-forbidden Pydantic schemas and exact semantic cross-file
  validation for identity, mode, feature sets/versions/dtypes, training recipe, calibration,
  gate, versions and timestamps. Symlinked artifact parents are rejected.
- Rejected valid evidence remains auditable. Invalid caller model evidence is rejected while
  the safe recomputed artifact is persisted; invalid/insufficient dataset evidence receives a
  rejected registry entry/receipt without inventing a model.

The strong and weak fixtures are synthetic contract tests only. The strong fixture exercises
the approval path but is not market-performance evidence and no persistent approved model or
model weight was added to the repository.

### Independent safety review

Read-only review initially identified model-binding, schema, registry resurrection, rejected
audit, sub-tolerance metric-boundary and symlink-escape issues. All CRITICAL/HIGH/MEDIUM
findings were fixed with regressions. Final review found no remaining CRITICAL/HIGH/MEDIUM;
reviewer did not edit files.

### Verification

- Focused registry/approval plus compatibility tests:
  `.venv/bin/pytest tests/unit/test_registries.py
  tests/unit/test_xgboost_approval.py tests/unit/test_retraining_workflow.py
  tests/unit/test_recommendations_api.py -q` → 38 passed.
- Full pytest: `.venv/bin/pytest tests/ -q`
  → 534 passed, 12 skipped, 1 failed.
- The sole failure remains the known baseline
  `tests/integration/test_db_migration.py::test_alembic_migration_lifecycle` because
  `infra/migrations/alembic.ini` is absent.
- `.venv/bin/ruff check .` → clean.
- `.venv/bin/mypy packages/ apps/` → 180 errors in 67 files, unchanged baseline.
- `git diff --check` → clean.
- Safety flags remain `False/False/False`.

### Next task

Proceed to Phase 5 only after the Phase 4E checkpoint is committed and pushed.

## Phase 4E — Runtime Inference

Status: **COMPLETE**

### Files changed

- `packages/retraining/xgboost_approval.py`
- `packages/retraining/xgboost_runtime.py`
- `tests/unit/test_xgboost_runtime.py`
- campaign progress/quality/task docs.

### Delivered

- Read-only `ApprovedModelRepository` accepts only the exact concrete approval service
  authority, never a mutable registry or structural provider.
- Registry entry, private service receipt and five-file artifact must all independently be
  `APPROVED`, exact-match and checksum-consistent. A direct-writer weak model paired with a
  forged registry entry, receipt and provider cannot cross the authority boundary.
- Exact model/version selection; omitted version is accepted only for one matching approved
  model and otherwise returns `AMBIGUOUS_APPROVED_MODEL`.
- Exact BTCUSDT/BTC-USDT, Binance venue, H4, one-bar horizon, mode, schema, feature
  names/order/dtypes and feature set version checks with no fallback or imputation.
- Missing, non-finite, stale, degraded and invalid feature inputs fail closed with stable
  reason codes. Unavailable outputs leave direction, probabilities, confidence, model ID,
  snapshot ID and timestamp null.
- Artifact bytes are read into one in-memory checksummed snapshot before JSON parsing and
  native model loading, eliminating a verify/read race.
- Runtime applies stored temperature to raw soft probabilities, revalidates normalization,
  uses the calibrated argmax direction, and defines confidence as exactly the maximum
  calibrated probability. Prediction time is the timezone-aware request snapshot as-of.

No API wiring, network call, Gemini/agent integration, private exchange API, order path or
live-trading change was introduced.

### Independent safety review

Read-only review found and drove fixes for forged structural-provider provenance and
unhandled disappearing/unreadable artifact failures. Final review reported no
CRITICAL/HIGH/MEDIUM findings. Its LOW calibration-coverage note was then closed by directly
comparing runtime output with independently calculated temperature-scaled probabilities.

### Verification

- `.venv/bin/pytest tests/unit/test_xgboost_runtime.py -q` → 7 passed.
- `.venv/bin/pytest tests/ -q` → 541 passed, 12 skipped, 1 failed.
- The sole failure remains the known missing `infra/migrations/alembic.ini` baseline issue.
- `.venv/bin/ruff check .` → clean.
- `.venv/bin/mypy packages/ apps/` → 180 errors in 67 files, unchanged baseline.
- `git diff --check` → clean; safety flags remain `False/False/False`.

### Phase 4 outcome

Phases 4A–4E are complete. Synthetic fixtures validate contracts only; no persistent approved
model or claim of real-market performance was created. Runtime is safely unavailable unless
an approval-service-backed artifact satisfies every exact gate.

## Phase 5 — Gemini Structured Provider

Status: **COMPLETE**

### Research and decisions

- Reused the existing `google-genai` dependency, chat provider boundary and LLM reliability
  patterns; no second SDK or real-provider test path was introduced.
- Official Gemini docs confirm JSON-schema/Pydantic structured output, but also require
  application semantic validation. Model availability and quotas are account-specific, so
  `GEMINI_MODEL` has no code default and must be configured.
- References:
  [structured output](https://ai.google.dev/gemini-api/docs/structured-output),
  [Python SDK](https://googleapis.github.io/python-genai/index.html),
  [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

### Delivered

- Provider-neutral typed structured request/result/health/telemetry contracts.
- Exact immutable append-only Prompt Registry with checksum and safe simple placeholders.
- Gemini adapter with lazy SDK client, strict JSON schema, duplicate-key/NaN/Infinity
  rejection, no string-to-number coercion, `extra=forbid` enforcement and Pydantic validation.
- Bounded timeout/retry/rate-limit/transient handling; invalid output is terminal.
- Configuration-only health reports `CONFIGURED`/`NOT_CONFIGURED`, not fabricated remote
  availability.
- Honest telemetry separates configured model ID from SDK-served model version and preserves
  token usage for completed invalid responses. Missing provider usage stays null.
- API keys are excluded from repr/serialization, raw SDK errors are not exposed, sensitive
  prompt names/values are blocked and `.env.example` contains no model/key value.
- Existing chat Gemini timeout/retry settings are now bounded and its model ID is also
  configuration-only.

No live Gemini API call was made. All provider tests use deterministic scripted transports.

### Independent safety review

Read-only review found strict-JSON ambiguity, unsafe formatter fields, served-model telemetry,
failed-output token accounting and unbounded legacy chat settings. All HIGH/MEDIUM findings
were fixed with regressions. Final review reported no remaining CRITICAL/HIGH/MEDIUM.

### Verification

- Phase-focused provider/LLM/chat tests → 60 passed.
- `.venv/bin/pytest tests/ -q` → 554 passed, 12 skipped, 1 failed.
- Sole failure remains the known missing `infra/migrations/alembic.ini`.
- `.venv/bin/ruff check .` → clean.
- `.venv/bin/mypy packages/ apps/` → 180 errors in 67 files.
- `git diff --check` → clean; safety flags remain `False/False/False`.

### Next task

Phase 6 — Specialist Agents: Technical, Derivatives and quantitative wrapper, using only
precomputed values and evidence references through the Phase 5 provider contract.

## Phase 6 — Specialist Agents

Status: **COMPLETE**

### Delivered

- Immutable append-only analysis evidence with exact category schemas, metric units/domains,
  feature-set versions, source lineage and point-in-time validation.
- Technical Agent consumes a complete technical snapshot plus coherent quantitative
  prediction evidence; Derivatives Agent consumes complete raw and derived derivatives data.
- Both LLM agents use versioned prompts, reject digits outside typed numeric claims, and
  validate every claim against the exact evidence ID/name/value/unit.
- Provider failures, invalid schemas, missing/stale/future/mixed/duplicate evidence return
  `UNAVAILABLE` with no fabricated analysis fields.
- Quantitative Agent is a deterministic wrapper over the exact Phase 4E approved runtime and
  emits its own probability/confidence evidence. The runtime now also rejects arbitrary
  repository implementations.

### Independent safety review

Read-only review identified free-text numeric bypasses, incomplete/arbitrary schemas,
approval-authority bypass, duplicate/mixed evidence, unit ambiguity, provider exception
leakage and an overly strict downstream probability sum. All CRITICAL/HIGH/MEDIUM findings
were fixed with regression coverage. Final review reported none remaining.

### Verification

- Specialist/runtime focused tests: 13 passed.
- Full pytest: 560 passed, 12 skipped, 1 known Alembic failure.
- Ruff clean; mypy remains the 180-error/67-file baseline.
- `git diff --check` clean; safety settings remain `False/False/False`.

### Next task

Phase 7 — bounded, evidence-only Bull–Bear Debate with persistent transcript and safe partial
failure handling.

## Phase 7 — Bull–Bear Debate

Status: **COMPLETE**

### Delivered

- Explicit Bull and Bear roles, maximum two rounds, exact stance validation and evidence-only
  arguments.
- Current-analysis/time validation, exact numeric claim matching, mandatory invalidation
  conditions and same-side new-evidence requirement.
- Append-only immutable transcript with prompt/model/token/latency telemetry and pre-call
  reservation/idempotent completed reruns.
- `COMPLETE`, `PARTIAL` and `FAILED` distinguish two-sided, one-sided and no-valid-argument
  outcomes. Provider failures never create a successful turn.

### Independent safety review

Initial review found masked one-sided failures, ambiguous assigned-side prompts, missing
invalidation requirements, naive timestamp crash, duplicate provider side effects and weak
duplicate detection. All HIGH/MEDIUM findings were corrected and regression-tested; final
review reported none remaining.

### Verification

- Offline debate tests: 6 passed.
- Full pytest: 566 passed, 12 skipped, 1 known Alembic failure.
- Ruff/diff clean; mypy remains the 180-error baseline.
- Safety flags remain `False/False/False`.

### Next task

Phase 8 — deterministic verification authority and code-based risk engine with independent
blocking decisions.

## Phase 8 — Verification & Risk

Status: **COMPLETE**

### Delivered

- Verification requires the exact three-specialist set and complete debate, re-resolves every
  evidence ID/time/status/category and re-matches every numeric claim.
- Confidence and volatility come only from verified quantitative/technical evidence.
- Risk Engine is code-only and binds analysis/time before conservative RR, position sizing,
  volatility, drawdown and exposure gates.
- Verification and Risk each independently veto; rejected results approve zero exposure.
- LONG-only schema keeps SHORT unavailable until dedicated safety/accounting coverage exists.

### Independent safety review

Review found unchecked debate references, incomplete specialist sets, caller-controlled
confidence/volatility, timestamp replay, inconsistent slippage RR, naive-time crash and
implicit short geometry. All HIGH/MEDIUM findings were fixed and regression-tested; final
review reported none remaining.

### Verification

- Focused verification/risk suites: 24 passed.
- Full pytest: 569 passed, 12 skipped, 1 known Alembic failure.
- Ruff/diff clean; mypy remains the 180-error baseline; safety flags are unchanged.

### Next task

Phase 9 — deterministic Manager gating and strict schema synthesis.

## Phase 9 — Manager Agent

Status: **COMPLETE**

### Delivered

- Deterministic synthesis with exact specialist/debate/verification/risk analysis-time
  matching and strict `LONG/HOLD/NO_DECISION` schema.
- Exact Verification and Risk authority chain with result digest relationships; Manager
  re-verifies canonical upstream inputs and rejects tampering/replay.
- No confidence or evidence on `NO_DECISION`; valid confidence is quantitative
  evidence-derived and Risk-approved.
- Specialist and debate invalidating conditions are retained; valid decisions cannot omit
  them.
- Immutable append-only snapshot with canonical fingerprint/idempotency.
- SHORT remains explicitly disabled pending short-specific risk/accounting approval.

### Independent safety review

Review identified authority-chain replay, missing invalidation lineage, unsafe naive-time
handling and order-sensitive idempotency. All HIGH/MEDIUM findings were fixed; final review
reported none remaining.

### Verification

- Manager/verification/risk focused tests: 7 passed.
- Full pytest: 573 passed, 12 skipped, 1 known Alembic failure.
- Ruff/diff clean; mypy remains baseline; safety flags unchanged.

### Next task

Phase 10 — expose the analysis surface through the existing API/dashboard stack with strict
error and empty-state contracts.

## Phase 10 — API & Dashboard

Status: **COMPLETE**

### Delivered

- Exact market/analysis/prediction/health API paths, locked bounded analysis persistence,
  stable errors and strict local CORS.
- Safe rejected execution snapshot exposes all agent/debate/verification/risk states when
  runtime is not configured, without inventing evidence or confidence.
- Dashboard can run analysis and inspect agents, debate, evidence, verification/risk,
  predictions and system health with loading/error/empty/unavailable states.
- Frontend test stack added; Vite/Vitest upgraded and dependency audit is clean.

### Independent safety review

Review identified placeholder-only inspection, wildcard credentialed CORS, store race/bounds,
unavailable/error inconsistency, superficial views and missing frontend behavior tests. All
HIGH/MEDIUM findings were fixed; final review reported none remaining.

### Verification

- API 3 passed; dashboard 3 passed; production build passed.
- npm audit: zero vulnerabilities.
- Full Python suite: 576 passed, 12 skipped, 1 known Alembic failure.
- Ruff/diff clean; safety flags unchanged.

### Next task

Phase 11 — validate and complete existing shadow scheduler/evaluation/idempotency controls.

## Phase 11 — Shadow Trading

Status: **COMPLETE**

### Delivered

- Automatic persisted-horizon scheduling (one bar by default), kill switch, store-wide
  claims, locked idempotency and append-only outcome transition history.
- Complete point-in-time candle-window validation with retryable missing/provider states.
- Runtime/replay namespace isolation.
- Persisted horizon labels/correctness plus barrier/timeout simulated return.
- Point-in-time periodic report with honest directional and per-agent correctness.

### Independent safety review

Review found arbitrary/optional horizons, incomplete-window fabrication, terminal transient
failure, replay contamination, profitability mislabeled as accuracy, non-temporal reports and
concurrency/lineage gaps. All HIGH/MEDIUM findings were fixed; final review reported none.

### Verification

- Shadow plus acceptance/domain focused tests: 34 passed.
- Full suite: 578 passed, 12 skipped, 1 known Alembic failure.
- Ruff/diff clean; safety flags unchanged.

### Next task

Phase 12 — validate deterministic paper accounting and irreversible live/private separation.

## Phase 12 — Paper Trading

Status: **COMPLETE**

### Delivered

- Retained the existing code-only risk sizing, session-isolated cash ledger, long-only
  position accounting, protective stop/take-profit exits and public-data paper pipeline.
- Deterministic paper order/fill identity and event-time execution with explicit fee/slippage.
- End-to-end fill idempotency across ledger, position, PnL and history; rejected fills remain
  retryable and terminal fills cannot be cancelled.
- Immutable equity curve, trade history and portfolio metrics including NAV, return, fees,
  realized/unrealized PnL, win rate and maximum drawdown.
- Durable position protection/valuation persistence, deterministic storage IDs and replay
  recovery; missing protection blocks recovery.

### Independent safety review

Final independent read-only review found no remaining CRITICAL/HIGH/MEDIUM issue after
correctness fixes. Reviewer did not edit files.

### Verification

- Focused paper/position/durability tests: 41 passed, 12 skipped.
- Full suite: 589 passed, 12 skipped, 1 known Alembic failure.
- PostgreSQL durability drills remain 12 skipped without `PAPER_DB_TEST_URL`.
- Ruff clean.
- Targeted mypy shows only three known shared baseline errors; no Phase 12-specific error.
- Diff clean; safety settings unchanged.

### Next task

Phase 13 — append-only experimental data capture, deterministic export and honest aggregate
reporting.

## Phase 13 — Experimental Data Collection

Status: **COMPLETE**

### Delivered

- Canonical checksummed capture for every required input, version, multi-agent decision,
  outcome, paper PnL, provider telemetry and data-quality field.
- Time-matured outcomes are independent append-only horizon events, so the original analysis
  is never rewritten and future information cannot enter its envelope.
- Reproducible experiment IDs and locked append-only persistence with exact-replay idempotency.
- Non-overwriting atomic JSONL export, explicit manual-audited retention and a data dictionary.
- Reports use only observed values and preserve nulls for unavailable outcomes/cost.

### Independent safety review

Independent read-only review found no remaining CRITICAL/HIGH/MEDIUM after fixes. Reviewer did
not edit files.

### Verification

- Experiment tests: 5 passed.
- Full suite: 594 passed, 12 skipped, 1 known Alembic failure.
- Targeted Ruff and mypy clean.
- Safety defaults remain false; no network, private API or trading path added.

### Next task

Phase 14 — feature-flagged advanced source protocols and safe-unavailable research expansion.

## Phase 14 — Advanced Expansion

Status: **COMPLETE (SAFE-UNAVAILABLE BY DEFAULT)**

### Delivered

- Feature-flagged, licensed, point-in-time provider/evidence contract for News, On-chain,
  Macro, Sentiment and Market Regime.
- Exact per-source schemas, three-clock lineage, provenance-domain license grants and a
  research-only five-agent coordinator.
- Safe disabled/unconfigured/provider-error/quality/lookahead handling.
- Exact research-only ETH model binding with no BTC fallback.
- Reflection and dynamic weighting are proposal-only, immutable and require approval; neither
  can change production configuration.

### Independent safety review

Independent read-only review found no remaining CRITICAL/HIGH/MEDIUM after fixes. Reviewer did
not edit files.

### Verification

- Advanced source/proposal tests: 11 passed.
- Full suite: 605 passed, 12 skipped, 1 known missing-Alembic-config failure.
- Targeted Ruff and mypy clean.
- All eight advanced flags and all three trading safety flags remain false.

### Next task

Phase 15 — thesis-ready structure and reproducibility protocol with every unavailable result
marked `PENDING_EVIDENCE`.

### Commit and push

- Phase 4A implementation commit: `4528293` (`docs: complete Phase 4A XGBoost design`).
- Phase 4B implementation commit: `f740f1b`
  (`feat: complete Phase 4B point-in-time dataset`).
- Phase 4C implementation commit: `217d6e7`
  (`feat: complete Phase 4C walk-forward training`).
- Phase 12 commit is recorded after the checkpoint is created.
- Push status: pushed successfully to `origin/main` on 2026-07-24.
- Pull request: not created, as required.
