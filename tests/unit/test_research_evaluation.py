"""Unit tests for packages/research/evaluation.py."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from packages.research.evaluation import (
    compute_classification_metrics,
    compute_trade_metrics,
    evaluate_subject_on_split,
    run_walk_forward_evaluation,
)

NOW = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)


def _labeled_table(n=100, seed=1, win_rate=0.6):
    rng = np.random.default_rng(seed)
    entry_times = [NOW + timedelta(hours=i) for i in range(n)]
    labels = rng.choice(["PROFIT", "LOSS", "TIMEOUT"], size=n, p=[win_rate * 0.7, (1 - win_rate) * 0.7, 0.3])
    net_return_bps = np.where(
        labels == "PROFIT", rng.uniform(20, 100, n),
        np.where(labels == "LOSS", rng.uniform(-100, -20, n), rng.uniform(-10, 10, n)),
    )
    probability_profit = np.clip(rng.uniform(0.3, 0.9, n) + (labels == "PROFIT") * 0.1, 0.01, 0.99)

    df = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"] * (n // 2) + ["ETHUSDT"] * (n - n // 2),
            "timeframe": ["1h"] * n,
            "entry_time": entry_times,
            "label_end_time": [t + timedelta(minutes=60) for t in entry_times],
            "label": labels,
            "net_return_bps": net_return_bps,
            "estimated_cost_bps": [22.0] * n,
            "market_regime": rng.choice(["TREND_UP", "SIDEWAYS"], size=n),
            "decision": True,
            "model_probability": probability_profit,
            "split": "test",
        }
    )
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["label_end_time"] = pd.to_datetime(df["label_end_time"], utc=True)
    return df


# --------------------------------------------------------------------------------------
# compute_trade_metrics
# --------------------------------------------------------------------------------------


def test_compute_trade_metrics_empty_returns_zero_trades():
    metrics = compute_trade_metrics(pd.DataFrame(columns=["net_return_bps", "entry_time"]))
    assert metrics.trade_count == 0
    assert metrics.win_rate is None


def test_compute_trade_metrics_basic_fields_populated():
    table = _labeled_table(n=200)
    metrics = compute_trade_metrics(table)

    assert metrics.trade_count == 200
    assert metrics.win_rate is not None
    assert metrics.net_pnl_bps is not None
    assert metrics.profit_factor is not None
    assert metrics.max_drawdown_pct is not None
    assert metrics.max_drawdown_pct >= 0
    assert metrics.average_holding_minutes == pytest.approx(60, abs=1)


def test_compute_trade_metrics_profit_factor_matches_manual_calculation():
    table = _labeled_table(n=300)
    metrics = compute_trade_metrics(table)

    wins = table[table["net_return_bps"] > 0]["net_return_bps"].sum()
    losses = -table[table["net_return_bps"] < 0]["net_return_bps"].sum()
    expected_pf = wins / losses
    assert float(metrics.profit_factor) == pytest.approx(expected_pf, rel=1e-6)


def test_compute_trade_metrics_max_drawdown_is_non_negative_and_zero_for_monotonic_gains():
    n = 20
    table = pd.DataFrame(
        {
            "entry_time": pd.to_datetime([NOW + timedelta(hours=i) for i in range(n)], utc=True),
            "net_return_bps": [10.0] * n,  # always positive -> no drawdown
        }
    )
    metrics = compute_trade_metrics(table)
    assert metrics.max_drawdown_pct == 0


# --------------------------------------------------------------------------------------
# compute_classification_metrics
# --------------------------------------------------------------------------------------


def test_compute_classification_metrics_bounded_values():
    table = _labeled_table(n=300)
    metrics = compute_classification_metrics(table, "model_probability", threshold=0.5)

    assert 0.0 <= metrics.precision <= 1.0
    assert 0.0 <= metrics.recall <= 1.0
    assert 0.0 <= metrics.f1 <= 1.0
    assert metrics.roc_auc is None or 0.0 <= metrics.roc_auc <= 1.0
    assert metrics.brier_score >= 0.0
    assert metrics.log_loss >= 0.0


def test_compute_classification_metrics_perfect_predictions():
    y_true = np.array([1] * 50 + [0] * 50)
    df = pd.DataFrame(
        {
            "label": np.where(y_true == 1, "PROFIT", "LOSS"),
            "model_probability": np.where(y_true == 1, 0.99, 0.01),
        }
    )
    metrics = compute_classification_metrics(df, "model_probability", threshold=0.5)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0


# --------------------------------------------------------------------------------------
# evaluate_subject_on_split / run_walk_forward_evaluation
# --------------------------------------------------------------------------------------


def test_evaluate_subject_on_split_uses_only_matching_split():
    table = _labeled_table(n=100)
    table.loc[table.index[:50], "split"] = "train"
    table.loc[table.index[50:], "split"] = "test"

    aggregate, breakdowns = evaluate_subject_on_split(table, "decision", "test")
    assert aggregate.trade_count == 50
    assert any(b.dimension == "symbol" for b in breakdowns)
    assert any(b.dimension == "timeframe" for b in breakdowns)
    assert any(b.dimension == "regime" for b in breakdowns)


def test_evaluate_subject_on_split_respects_decision_column_false_excludes_rows():
    table = _labeled_table(n=50)
    table["decision"] = False  # baseline that never trades
    aggregate, _ = evaluate_subject_on_split(table, "decision", "test")
    assert aggregate.trade_count == 0


def test_run_walk_forward_evaluation_aggregates_across_folds():
    fold1 = _labeled_table(n=60, seed=1)
    fold2 = _labeled_table(n=60, seed=2)

    report = run_walk_forward_evaluation(
        subject_name="logreg_v1",
        subject_type="MODEL",
        fold_tables=[fold1, fold2],
        dataset_checksum="abc123",
        config_hash="cfg-hash",
        decision_column="decision",
        probability_column="model_probability",
        now=NOW,
    )

    assert report.walk_forward_windows == 2
    assert report.aggregate_metrics.trade_count == 120
    window_breakdowns = [b for b in report.breakdowns if b.dimension == "window"]
    assert len(window_breakdowns) == 2
    assert report.calibration is not None
    assert 0.0 <= report.calibration.calibration_score <= 1.0


def test_run_walk_forward_evaluation_flags_multiple_testing_when_many_experiments_tried():
    fold1 = _labeled_table(n=30, seed=3)
    report = run_walk_forward_evaluation(
        subject_name="logreg_v1", subject_type="MODEL", fold_tables=[fold1],
        dataset_checksum="abc", config_hash="cfg", decision_column="decision",
        experiments_tried=50, now=NOW,
    )
    assert report.multiple_testing_warning is not None


def test_run_walk_forward_evaluation_baseline_has_no_calibration_report():
    fold1 = _labeled_table(n=30, seed=4)
    report = run_walk_forward_evaluation(
        subject_name="BUY_AND_HOLD", subject_type="BASELINE", fold_tables=[fold1],
        dataset_checksum="abc", config_hash="cfg", decision_column="decision",
        probability_column=None, now=NOW,
    )
    assert report.calibration is None
    assert report.subject_type == "BASELINE"
