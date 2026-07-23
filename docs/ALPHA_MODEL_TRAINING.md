# ALPHA RESEARCH — MODEL TRAINING

## 1. Feature timing

`packages/research/feature_dataset.py::build_feature_table` walks
`packages.features.pipeline.feature_pipeline.compute()` — the SAME feature engine the
live paper-trading/backtest/recommendation paths use — forward one closed candle at a
time. Point-in-time correctness is enforced by two independent layers:

1. This module only ever slices the candle history to `history[: i + 1]` before calling
   `feature_pipeline.compute()` — a candle with a later `open_time` is never even present
   in memory when a feature is computed.
2. `FeaturePipeline.compute()` itself additionally filters to `close_time <= as_of_time`.

`test_feature_table_never_changes_when_future_candles_are_appended` is the leakage test:
it builds the feature table twice, once from a truncated candle list and once from the
full list, and asserts every feature value that exists in both runs is byte-identical.

The first `warmup_periods` (config, default 60) candles per `(symbol, timeframe)` group
are skipped — not enough trailing history for stable indicators (e.g. `ema_20_slope`,
`adx_14`). Missing individual feature values are zero-filled (matching the runtime
`packages.prediction.feature_adapter.to_feature_vector` policy exactly, for consistency
between training and inference), and a `had_missing_feature` column records which rows
were affected — never silently indistinguishable from a genuine zero.

## 2. Model — Logistic Regression (Version 1)

`packages/research/training.py`. Two independent one-vs-rest binary fits:

- `up_coefficients`/`up_intercept`: PROFIT-vs-rest
- `down_coefficients`/`down_intercept`: LOSS-vs-rest

This is exactly the shape `packages.prediction.direction_model
.LogisticRegressionDirectionModel.predict_proba` already expects — no adapter code
exists or is needed between training output and runtime inference input.
`test_train_logistic_direction_weights_produces_usable_weights` proves a freshly trained
artifact loads directly into that existing runtime class.

A `LinearRegression` return-magnitude model is trained the same way, producing
`LinearRegressionWeights` for `packages.prediction.return_model.LinearReturnModel`.

`scikit-learn` (the `research` optional dependency group, `pyproject.toml`) is imported
lazily inside training functions, never at module import time, and never imported by
`packages/prediction/*` inference code — inference is pure arithmetic over plain floats.

**XGBoost/LightGBM were not implemented.** The plan permits this ("Optional second model,
only if dependency and environment support are clean... Do not add both merely for
breadth"). Logistic Regression already satisfies the required Version 1 baseline; adding
a second heavy ML dependency purely for breadth, without a specific reason to believe the
extra model capacity would matter at this data scale, was judged not worth the added
environment/artifact-format complexity for this phase. This is a deliberate scope
decision, not an oversight — see the final report's remaining-gaps section.

## 3. Why no pickle/joblib

A trained artifact in this pipeline is always the *fitted coefficients* (plain floats),
serialized through the EXISTING `LogisticRegressionWeights`/`LinearRegressionWeights`
Pydantic models — never a pickled `sklearn` estimator object. There is therefore no
untrusted-deserialization trust boundary to manage for Version 1
(`packages/research/artifacts.py` module docstring). If a future non-linear model (e.g. a
tree ensemble) is added, its inference-time artifact format needs its own explicit
decision (e.g. ONNX) — pickle should not become the default just because it's
convenient.

## 4. Artifact lineage

Every `ModelArtifactRecord` (`packages/research/models.py`) records: `model_id`,
`model_type`, `model_version`, `feature_version`, `dataset_checksum`, `label_version`,
`hyperparameters`, `random_seed`, `train_period`/`validation_period`/`test_period`
(the exact split window boundaries), `code_commit`, `artifact_path`, `artifact_checksum`
(SHA-256 over the direction + return weights JSON, `packages.research.training
.weights_checksum`), `config_hash`, `created_at`.

Storage: `artifacts/models/{model_id}.json` (record) +
`artifacts/models/{model_id}_direction.weights.json` +
`artifacts/models/{model_id}_return.weights.json` (plain JSON, never pickle).

## 5. Random seeds

`ModelConfig.random_seed` (default 42) is passed to `LogisticRegression(random_state=...)`
explicitly. `LinearRegression` (ordinary least squares, no closed-form randomness) needs
no seed. Every training run's exact hyperparameters are recorded on the
`ModelArtifactRecord`, so a run is reproducible from its artifact metadata alone.

## 6. Known limitations

- No hyperparameter search is implemented; `ModelConfig.hyperparameters` is a fixed
  dict per config file. Any manual comparison across configs should be recorded via
  `packages.research.overfitting.ExperimentTracker` so the resulting `experiments_tried`
  count on an `EvaluationReport` stays honest (see `docs/ALPHA_EVIDENCE_POLICY.md`).
- Class imbalance (TIMEOUT typically dominates PROFIT/LOSS — see the real smoke run in
  the implementation report) is not corrected for (no class weighting, no resampling).
