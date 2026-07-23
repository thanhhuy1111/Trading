"""Trains the required baseline model: Logistic Regression.

Fits directly into the EXISTING packages.prediction inference contracts --
`LogisticRegressionWeights` / `LinearRegressionWeights` -- so the trained artifact this
module produces is loadable, without any adapter code, by
`LogisticRegressionDirectionModel` / `LinearReturnModel` at inference time
(packages/prediction/direction_model.py, packages/prediction/return_model.py). Training
itself uses scikit-learn (the "research" extra, training-time only -- see
pyproject.toml); inference never imports scikit-learn.

Two independent one-vs-rest binary fits (PROFIT-vs-rest, LOSS-vs-rest) produce
`up_coefficients`/`down_coefficients` -- this is exactly the shape
`LogisticRegressionDirectionModel.predict_proba` already expects, not a new format.

`scikit-learn` is imported lazily inside functions, not at module top level, so importing
`packages.research.training` doesn't hard-require the research extra to be installed
merely to inspect this module.
"""

from datetime import datetime, timezone
from typing import List

import pandas as pd

from packages.prediction.direction_model import LogisticRegressionWeights
from packages.prediction.return_model import LinearRegressionWeights
from packages.research.checksums import checksum_json, get_code_commit
from packages.research.config import ModelConfig
from packages.research.exceptions import InsufficientDataError
from packages.research.models import ModelArtifactRecord, SplitWindow


def prepare_training_matrix(
    feature_table: pd.DataFrame,
    label_table: pd.DataFrame,
    feature_names: List[str],
    horizon_minutes: int,
) -> pd.DataFrame:
    """Joins the feature table to the label table for one horizon, on
    (symbol, timeframe, open_time == entry_open_time). Returns the merged rows only --
    callers slice feature/target columns out of it.
    """
    labels_for_horizon = label_table[label_table["horizon_minutes"] == horizon_minutes]
    merged = feature_table.merge(
        labels_for_horizon,
        left_on=["symbol", "timeframe", "open_time"],
        right_on=["symbol", "timeframe", "entry_open_time"],
        how="inner",
        suffixes=("", "_label"),
    )
    return merged


def _feature_matrix(merged: pd.DataFrame, feature_names: List[str]):
    return merged[[f"feature__{name}" for name in feature_names]].to_numpy()


def train_logistic_direction_weights(
    merged_train: pd.DataFrame,
    feature_names: List[str],
    model_version: str,
    hyperparameters: dict,
    random_seed: int,
) -> LogisticRegressionWeights:
    from sklearn.linear_model import LogisticRegression

    if merged_train.empty:
        raise InsufficientDataError("Cannot train logistic regression on an empty training set")

    X = _feature_matrix(merged_train, feature_names)
    y_up = (merged_train["label"] == "PROFIT").astype(int).to_numpy()
    y_down = (merged_train["label"] == "LOSS").astype(int).to_numpy()

    if len(set(y_up.tolist())) < 2 or len(set(y_down.tolist())) < 2:
        raise InsufficientDataError(
            "Training set has only one class present for PROFIT-vs-rest or LOSS-vs-rest "
            "-- cannot fit a meaningful logistic regression (need both outcomes represented)"
        )

    up_clf = LogisticRegression(random_state=random_seed, **hyperparameters).fit(X, y_up)
    down_clf = LogisticRegression(random_state=random_seed, **hyperparameters).fit(X, y_down)

    return LogisticRegressionWeights(
        model_version=model_version,
        feature_names=list(feature_names),
        up_coefficients=[float(v) for v in up_clf.coef_[0]],
        up_intercept=float(up_clf.intercept_[0]),
        down_coefficients=[float(v) for v in down_clf.coef_[0]],
        down_intercept=float(down_clf.intercept_[0]),
    )


def train_linear_return_weights(
    merged_train: pd.DataFrame,
    feature_names: List[str],
    model_version: str,
) -> LinearRegressionWeights:
    from sklearn.linear_model import LinearRegression

    if merged_train.empty:
        raise InsufficientDataError("Cannot train return regressor on an empty training set")

    X = _feature_matrix(merged_train, feature_names)
    y = merged_train["net_return_bps"].to_numpy()

    reg = LinearRegression().fit(X, y)
    return LinearRegressionWeights(
        model_version=model_version,
        feature_names=list(feature_names),
        coefficients=[float(v) for v in reg.coef_],
        intercept=float(reg.intercept_),
    )


def build_model_artifact_record(
    *,
    model_config: ModelConfig,
    feature_version: str,
    dataset_checksum: str,
    label_version: str,
    train_window: SplitWindow,
    validation_window: SplitWindow,
    test_window: SplitWindow,
    artifact_path: str,
    artifact_checksum: str,
    config_hash: str,
    now: "datetime | None" = None,
) -> ModelArtifactRecord:
    return ModelArtifactRecord(
        model_type=model_config.model_type,
        model_version=model_config.model_version,
        feature_version=feature_version,
        dataset_checksum=dataset_checksum,
        label_version=label_version,
        hyperparameters=dict(model_config.hyperparameters),
        random_seed=model_config.random_seed,
        train_period=f"{train_window.start.isoformat()}..{train_window.end.isoformat()}",
        validation_period=f"{validation_window.start.isoformat()}..{validation_window.end.isoformat()}",
        test_period=f"{test_window.start.isoformat()}..{test_window.end.isoformat()}",
        code_commit=get_code_commit(),
        artifact_path=artifact_path,
        artifact_checksum=artifact_checksum,
        config_hash=config_hash,
        created_at=now or datetime.now(timezone.utc),
    )


def weights_checksum(direction_weights: LogisticRegressionWeights, return_weights: LinearRegressionWeights) -> str:
    return checksum_json(
        {"direction": direction_weights.model_dump(), "return": return_weights.model_dump()}
    )
