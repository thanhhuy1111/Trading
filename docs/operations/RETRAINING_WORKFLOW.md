# Retraining Workflow (Phase 12)

`packages/retraining/workflow.py: RetrainingWorkflow.run_training_job()`. A small
fixture-based training smoke test is the acceptance bar for this task
(`tests/unit/test_retraining_workflow.py`) - not an accuracy campaign. No large hyperparameter
search: exactly one small logistic-regression model, fit via a bounded (~200-iteration)
full-batch gradient descent, dependency-free (stdlib `math` only).

## Stages (all recorded in `RetrainingJobResult.stages_completed`)

1. **`DATASET_SELECTED`** - candles are caller-provided; this workflow never fetches anything
   live itself.
2. **`CHECKSUM_COMPUTED`** - SHA-256 over sorted `(close_time, close_price)` pairs.
3. **`FEATURES_GENERATED`** - past-only, via the existing `packages.features.pipeline.feature_pipeline`
   with a bounded 60-bar rolling window per row, same pattern `packages.research.candidate_dry_run`
   already uses.
4. **`LABELS_GENERATED`** - next-bar return sign. Intentionally forward-looking - that is what a
   supervised label is. This is distinct from and does not violate rule 4's "no future-derived
   FEATURES": the feature vector for bar *i* only ever reads candles up to and including bar
   *i*; only the label reaches one bar forward.
5. **`TIME_SERIES_SPLIT_WITH_PURGE_EMBARGO`** - reuses the existing, already-tested
   `packages.backtest.walk_forward.WalkForwardRunner` (train 60% / validation 20% / test 20%,
   with purge and embargo gaps between them) rather than a second split implementation.
6. **`MODEL_TRAINED`** - bounded gradient descent (`_fit_logistic_regression`).
7. **`VALIDATED`** - accuracy on the validation fold.
8. **`CALIBRATED`** - identity in this baseline (no Platt fit); documented as such, not a
   claim of a calibrated model.
9. **`TESTED`** - accuracy on the held-out test fold.
10. **`ARTIFACT_PUBLISHED_RESEARCH_ONLY`** - the artifact (feature_names, coefficients,
    intercept, calibration, decision_threshold - the exact format
    `packages.intelligence.meta_label.LogisticRegressionMetaLabelService` already documents
    and can load) is registered in `model_registry` at `RegistryEntryStatus.RESEARCH_ONLY`.
    **No code path in this module can reach `APPROVED`.**
11. **`EVIDENCE_REVIEW_REQUESTED`** - an `EvidenceRecord` is registered at
    `EvidenceStatus.INSUFFICIENT`, explicitly awaiting human review, tied to the exact
    `(strategy, symbol, timeframe, model_type, model_version, feature_version, label_version,
    dataset_checksum, gate_version, config_hash, code_commit)` key the new model produced.

## Rollback

`rollback_model_version(registry, name, version, actor, reason)` - the only rollback path this
task provides. It **only ever disables** a specific `(name, version)`; it requires a named
human actor (raises `ValueError` without one) and is itself subject to the registry's normal
status-transition rules (`RESEARCH_ONLY -> DISABLED` is allowed; a second rollback attempt on
an already-`DISABLED` entry raises `InvalidStatusTransitionError`, not a silent no-op).
Restoring an older version to active use is a separate, ordinary `transition_status()` call on
that older entry - this function cannot be used to promote anything.

## What this task deliberately does not do

- No large campaign, no hyperparameter search, no claim of model accuracy.
- No automatic promotion, ever - promotion stays a separate, human-gated registry operation.
- No live data fetch inside the workflow - the caller supplies candles.
