"""Chronological train/validation/test splits with purge and embargo.

Wraps `packages.backtest.walk_forward.walk_forward_runner.generate_folds` -- the SAME
fold-generation logic backtest walk-forward sessions already use -- rather than
reimplementing window arithmetic. A plain (non-walk-forward) chronological split is just
`num_folds=1` of the same generator, so there is only one implementation to trust.

Purge/embargo sizing: a label's outcome is only known at `label_end_time`, which can be up
to `max(horizons_minutes)` after its `entry_time`. If the purge gap between train and
validation were shorter than the longest label horizon, a label entered near the end of
the training window could have its *outcome* determined by candles inside the validation
window -- i.e. the model would be validated partly on its own training signal. This module
therefore refuses to use a `purge_hours` smaller than the longest configured label horizon
(it widens it and records that it did so, never silently uses an unsafe value).
"""

import math
from datetime import datetime
from typing import List
from uuid import uuid4

import pandas as pd

from packages.backtest.walk_forward import walk_forward_runner
from packages.research.config import LabelConfig, SplitConfig
from packages.research.exceptions import InsufficientDataError
from packages.research.models import SplitWindow, WalkForwardWindowPlan


def effective_purge_hours(split_config: SplitConfig, label_config: LabelConfig) -> int:
    min_required = math.ceil(max(label_config.horizons_minutes) / 60) if label_config.horizons_minutes else 0
    return max(split_config.purge_hours, min_required)


def plan_walk_forward_windows(
    start_time: datetime,
    end_time: datetime,
    split_config: SplitConfig,
    label_config: LabelConfig,
) -> List[WalkForwardWindowPlan]:
    if end_time <= start_time:
        raise InsufficientDataError("end_time must be after start_time to plan splits")

    purge_hours = effective_purge_hours(split_config, label_config)
    folds = walk_forward_runner.generate_folds(
        session_id=uuid4(),
        start_time=start_time,
        end_time=end_time,
        num_folds=split_config.num_folds,
        purge_hours=purge_hours,
        embargo_hours=split_config.embargo_hours,
    )

    plans = []
    for fold in folds:
        window_too_short = (
            fold.train_end <= fold.train_start
            or fold.validation_end <= fold.validation_start
            or fold.test_end <= fold.test_start
        )
        if window_too_short:
            raise InsufficientDataError(
                f"Fold {fold.fold_number}: date range too short for purge_hours={purge_hours}, "
                f"embargo_hours={split_config.embargo_hours}, num_folds={split_config.num_folds}"
            )
        plans.append(
            WalkForwardWindowPlan(
                fold_number=fold.fold_number,
                train=SplitWindow(name="train", start=fold.train_start, end=fold.train_end),
                validation=SplitWindow(name="validation", start=fold.validation_start, end=fold.validation_end),
                test=SplitWindow(name="test", start=fold.test_start, end=fold.test_end),
                purge_hours=purge_hours,
                embargo_hours=split_config.embargo_hours,
            )
        )
    return plans


def plan_chronological_split(
    start_time: datetime,
    end_time: datetime,
    split_config: SplitConfig,
    label_config: LabelConfig,
) -> WalkForwardWindowPlan:
    """A single train/validation/test split -- num_folds=1 of the walk-forward planner."""
    single_fold_config = split_config.model_copy(update={"num_folds": 1})
    plans = plan_walk_forward_windows(start_time, end_time, single_fold_config, label_config)
    return plans[0]


def assign_split_membership(label_table: pd.DataFrame, window: WalkForwardWindowPlan) -> pd.DataFrame:
    """Adds a `split` column ("train" | "validation" | "test" | None) to a copy of
    `label_table`, based on which window each row's `entry_time` falls in. Rows outside
    all three windows get `split=None` and are excluded from any downstream training/
    evaluation by callers filtering on this column.
    """
    if label_table.empty:
        out = label_table.copy()
        out["split"] = pd.Series(dtype="object")
        return out

    def _classify(entry_time: pd.Timestamp) -> "str | None":
        t = entry_time.to_pydatetime() if hasattr(entry_time, "to_pydatetime") else entry_time
        if window.train.start <= t < window.train.end:
            return "train"
        if window.validation.start <= t < window.validation.end:
            return "validation"
        if window.test.start <= t < window.test.end:
            return "test"
        return None

    out = label_table.copy()
    out["split"] = out["entry_time"].apply(_classify)
    return out


def verify_purge_embargo(labeled_table: pd.DataFrame, window: WalkForwardWindowPlan) -> None:
    """Raises AssertionError if the purge/embargo invariant is violated:
        max(train label_end_time)      < validation.start
        max(validation label_end_time) < test.start
    A no-op (nothing to check) if a split has zero rows.
    """
    train_rows = labeled_table[labeled_table["split"] == "train"]
    validation_rows = labeled_table[labeled_table["split"] == "validation"]

    if not train_rows.empty:
        max_train_label_end = train_rows["label_end_time"].max()
        max_train_label_end = (
            max_train_label_end.to_pydatetime()
            if hasattr(max_train_label_end, "to_pydatetime")
            else max_train_label_end
        )
        assert max_train_label_end < window.validation.start, (
            f"PURGE_VIOLATION: max train label_end_time {max_train_label_end} "
            f">= validation start {window.validation.start}"
        )

    if not validation_rows.empty:
        max_validation_label_end = validation_rows["label_end_time"].max()
        max_validation_label_end = (
            max_validation_label_end.to_pydatetime()
            if hasattr(max_validation_label_end, "to_pydatetime")
            else max_validation_label_end
        )
        assert max_validation_label_end < window.test.start, (
            f"PURGE_VIOLATION: max validation label_end_time {max_validation_label_end} "
            f">= test start {window.test.start}"
        )
