# Crypto Multi-Agent Trading Advisor — Progress

## Current state

- Branch: `main`
- Current phase: Phase 4 — XGBoost
- Last completed task: 4D — Approval & Artifact
- Next task: 4E — Runtime Inference
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

Implement Phase 4E read-only runtime inference. It must dual-verify exact registry state,
trusted receipt and artifact; otherwise return `UNAVAILABLE` with a stable reason code.

### Commit and push

- Phase 4A implementation commit: `4528293` (`docs: complete Phase 4A XGBoost design`).
- Phase 4B implementation commit: `f740f1b`
  (`feat: complete Phase 4B point-in-time dataset`).
- Phase 4C implementation commit: `217d6e7`
  (`feat: complete Phase 4C walk-forward training`).
- Push status: pushed successfully to `origin/main` on 2026-07-24.
- Pull request: not created, as required.
