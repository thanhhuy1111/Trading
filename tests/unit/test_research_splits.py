"""Unit tests for packages/research/splits.py -- purge/embargo chronology guarantees."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from packages.research.config import LabelConfig, SplitConfig
from packages.research.exceptions import InsufficientDataError
from packages.research.splits import (
    assign_split_membership,
    effective_purge_hours,
    plan_chronological_split,
    plan_walk_forward_windows,
    verify_purge_embargo,
)

NOW = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)


def test_effective_purge_hours_widens_when_config_too_small():
    split_config = SplitConfig(purge_hours=1, embargo_hours=1)
    label_config = LabelConfig(horizons_minutes=[60, 240, 720])  # max 720min = 12h
    assert effective_purge_hours(split_config, label_config) == 12


def test_effective_purge_hours_respects_larger_configured_value():
    split_config = SplitConfig(purge_hours=48, embargo_hours=1)
    label_config = LabelConfig(horizons_minutes=[60])
    assert effective_purge_hours(split_config, label_config) == 48


def test_plan_walk_forward_windows_produces_requested_fold_count():
    split_config = SplitConfig(num_folds=3, purge_hours=24, embargo_hours=24)
    label_config = LabelConfig(horizons_minutes=[60])
    plans = plan_walk_forward_windows(NOW - timedelta(days=180), NOW, split_config, label_config)
    assert len(plans) == 3
    assert [p.fold_number for p in plans] == [1, 2, 3]


def test_plan_walk_forward_windows_windows_are_chronological_within_a_fold():
    split_config = SplitConfig(num_folds=2, purge_hours=24, embargo_hours=24)
    label_config = LabelConfig(horizons_minutes=[60])
    plans = plan_walk_forward_windows(NOW - timedelta(days=120), NOW, split_config, label_config)
    for plan in plans:
        assert plan.train.start < plan.train.end <= plan.validation.start
        assert plan.validation.start < plan.validation.end <= plan.test.start
        assert plan.test.start < plan.test.end


def test_plan_walk_forward_windows_raises_when_range_too_short():
    split_config = SplitConfig(num_folds=5, purge_hours=200, embargo_hours=200)
    label_config = LabelConfig(horizons_minutes=[60])
    with pytest.raises(InsufficientDataError):
        plan_walk_forward_windows(NOW - timedelta(hours=10), NOW, split_config, label_config)


def test_plan_chronological_split_is_a_single_fold():
    split_config = SplitConfig(num_folds=5, purge_hours=24, embargo_hours=24)  # num_folds ignored
    label_config = LabelConfig(horizons_minutes=[60])
    plan = plan_chronological_split(NOW - timedelta(days=60), NOW, split_config, label_config)
    assert plan.fold_number == 1
    assert plan.train.start < plan.train.end <= plan.validation.start
    assert plan.validation.end <= plan.test.start


# --------------------------------------------------------------------------------------
# assign_split_membership / verify_purge_embargo
# --------------------------------------------------------------------------------------


def _window():
    split_config = SplitConfig(num_folds=1, purge_hours=24, embargo_hours=24)
    label_config = LabelConfig(horizons_minutes=[60])
    return plan_chronological_split(NOW - timedelta(days=60), NOW, split_config, label_config)


def _label_row(entry_time, label_end_time):
    return {
        "symbol": "BTCUSDT", "timeframe": "1h", "entry_open_time": entry_time, "entry_time": entry_time,
        "horizon_minutes": 60, "entry_reference_price": "50000", "upper_barrier": "51000",
        "lower_barrier": "49000", "time_barrier": entry_time + timedelta(hours=1),
        "first_barrier_hit": "TIME", "gross_return_bps": 0.0, "estimated_cost_bps": 22.0,
        "net_return_bps": -22.0, "label": "TIMEOUT", "label_end_time": label_end_time,
    }


def test_assign_split_membership_classifies_rows_correctly():
    window = _window()
    mid_train = window.train.start + (window.train.end - window.train.start) / 2
    mid_validation = window.validation.start + (window.validation.end - window.validation.start) / 2
    mid_test = window.test.start + (window.test.end - window.test.start) / 2
    outside = window.test.end + timedelta(days=5)

    df = pd.DataFrame(
        [
            _label_row(mid_train, mid_train + timedelta(minutes=30)),
            _label_row(mid_validation, mid_validation + timedelta(minutes=30)),
            _label_row(mid_test, mid_test + timedelta(minutes=30)),
            _label_row(outside, outside + timedelta(minutes=30)),
        ]
    )
    for col in ("entry_open_time", "entry_time", "time_barrier", "label_end_time"):
        df[col] = pd.to_datetime(df[col], utc=True)

    classified = assign_split_membership(df, window)
    values = list(classified["split"])
    assert values[:3] == ["train", "validation", "test"]
    assert pd.isna(values[3])


def test_verify_purge_embargo_passes_for_well_formed_split():
    window = _window()
    mid_train = window.train.start + (window.train.end - window.train.start) / 2
    mid_validation = window.validation.start + (window.validation.end - window.validation.start) / 2

    df = pd.DataFrame(
        [
            _label_row(mid_train, mid_train + timedelta(minutes=30)),
            _label_row(mid_validation, mid_validation + timedelta(minutes=30)),
        ]
    )
    for col in ("entry_open_time", "entry_time", "time_barrier", "label_end_time"):
        df[col] = pd.to_datetime(df[col], utc=True)
    classified = assign_split_membership(df, window)

    verify_purge_embargo(classified, window)  # should not raise


def test_verify_purge_embargo_detects_leaking_train_label():
    """A train-split row whose label_end_time reaches into the validation window must be
    caught -- this is the exact failure mode the purge gap exists to prevent.
    """
    window = _window()
    mid_train = window.train.start + (window.train.end - window.train.start) / 2
    leaking_end_time = window.validation.start + timedelta(hours=1)  # reaches past validation.start

    df = pd.DataFrame([_label_row(mid_train, leaking_end_time)])
    for col in ("entry_open_time", "entry_time", "time_barrier", "label_end_time"):
        df[col] = pd.to_datetime(df[col], utc=True)
    df["split"] = "train"  # force it into train regardless of assign_split_membership

    with pytest.raises(AssertionError, match="PURGE_VIOLATION"):
        verify_purge_embargo(df, window)
