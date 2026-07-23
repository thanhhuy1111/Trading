"""Walk-forward evaluation harness: turns a labeled+decisioned table into a typed
`EvaluationReport` with aggregate metrics and symbol/timeframe/regime/probability-bucket/
window breakdowns, for both the trained model and every baseline.

Trade-level metrics (Sharpe/Sortino/Calmar) are computed on the PER-TRADE `net_return_bps`
sequence, not annualized -- trade events from a triple-barrier label are irregularly
spaced in time (a TIMEOUT can end far later than a barrier touch), so naively annualizing
by a fixed number of "periods per year" would misrepresent risk-adjusted return. See
docs/ALPHA_WALK_FORWARD_VALIDATION.md for the exact convention and its limitations.

`max_drawdown_pct` is computed on a synthetic unit-sized cumulative-bps equity curve
(each taken trade contributes its net_return_bps, summed in entry-time order) -- this
approximates the drawdown of a strategy that risks a constant unit per trade and
reinvests nothing, which is a real (if simplified) risk statistic, not a NAV-based
backtest drawdown like packages.backtest.metrics computes for equity-curve backtests.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

import pandas as pd

from packages.research.calibration import build_calibration_report, fit_calibration
from packages.research.checksums import get_code_commit
from packages.research.models import EvaluationBreakdown, EvaluationMetrics, EvaluationReport


def _dec(x: Optional[float]) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return Decimal(str(round(float(x), 6)))


def compute_trade_metrics(taken_rows: pd.DataFrame) -> EvaluationMetrics:
    trade_count = len(taken_rows)
    if trade_count == 0:
        return EvaluationMetrics(trade_count=0)

    returns = taken_rows["net_return_bps"].astype(float)
    wins = taken_rows[taken_rows["net_return_bps"] > 0]
    losses = taken_rows[taken_rows["net_return_bps"] < 0]

    win_rate = _dec(len(wins) / trade_count * 100.0)
    gross_win = float(wins["net_return_bps"].sum())
    gross_loss = float(-losses["net_return_bps"].sum())
    profit_factor = _dec(gross_win / gross_loss) if gross_loss > 0 else None

    net_pnl_bps = _dec(returns.sum())
    average_net_return_bps = _dec(returns.mean())
    expectancy_bps = average_net_return_bps

    std = returns.std(ddof=1) if trade_count > 1 else 0.0
    sharpe = _dec(returns.mean() / std) if std and std > 0 else None

    downside = returns[returns < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else 0.0
    sortino = _dec(returns.mean() / downside_std) if downside_std and downside_std > 0 else None

    ordered = taken_rows.sort_values("entry_time")["net_return_bps"].astype(float).cumsum()
    running_max = ordered.cummax()
    drawdown_bps = (running_max - ordered)
    max_dd_bps = float(drawdown_bps.max()) if len(drawdown_bps) else 0.0
    max_drawdown_pct = _dec(max_dd_bps / 100.0)  # 100 bps == 1 pct
    calmar = _dec(float(net_pnl_bps) / max_dd_bps) if net_pnl_bps is not None and max_dd_bps > 0 else None

    total_fees_bps = (
        _dec(taken_rows["estimated_cost_bps"].sum()) if "estimated_cost_bps" in taken_rows.columns else None
    )

    if {"label_end_time", "entry_time"}.issubset(taken_rows.columns):
        holding_minutes = (taken_rows["label_end_time"] - taken_rows["entry_time"]).dt.total_seconds() / 60.0
        average_holding_minutes = _dec(holding_minutes.mean())
    else:
        average_holding_minutes = None

    return EvaluationMetrics(
        trade_count=trade_count,
        win_rate=win_rate,
        net_pnl_bps=net_pnl_bps,
        average_net_return_bps=average_net_return_bps,
        expectancy_bps=expectancy_bps,
        profit_factor=profit_factor,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown_pct=max_drawdown_pct,
        turnover=Decimal(trade_count),
        total_fees_bps=total_fees_bps,
        average_holding_minutes=average_holding_minutes,
    )


def compute_classification_metrics(
    rows: pd.DataFrame, probability_column: str, threshold: float = 0.5
) -> EvaluationMetrics:
    """Only meaningful for a MODEL (which has a probability column) -- baselines produce
    a boolean decision, not a probability, so this is never called for them.
    """
    from sklearn.metrics import f1_score, log_loss, precision_score, recall_score, roc_auc_score

    y_true = (rows["label"] == "PROFIT").astype(int).to_numpy()
    y_prob = rows[probability_column].astype(float).to_numpy()
    y_pred = (y_prob >= threshold).astype(int)

    metrics_kwargs = {}
    if len(set(y_true.tolist())) >= 2:
        metrics_kwargs["precision"] = float(precision_score(y_true, y_pred, zero_division=0))
        metrics_kwargs["recall"] = float(recall_score(y_true, y_pred, zero_division=0))
        metrics_kwargs["f1"] = float(f1_score(y_true, y_pred, zero_division=0))
        try:
            metrics_kwargs["roc_auc"] = float(roc_auc_score(y_true, y_prob))
        except ValueError:
            metrics_kwargs["roc_auc"] = None
        metrics_kwargs["brier_score"] = float(((y_prob - y_true) ** 2).mean())
        metrics_kwargs["log_loss"] = float(log_loss(y_true, y_prob, labels=[0, 1]))

    return EvaluationMetrics(trade_count=len(rows), **metrics_kwargs)


def _merge_metrics(base: EvaluationMetrics, extra: EvaluationMetrics) -> EvaluationMetrics:
    merged = base.model_dump()
    for key in ("precision", "recall", "f1", "roc_auc", "brier_score", "log_loss"):
        value = getattr(extra, key)
        if value is not None:
            merged[key] = value
    return EvaluationMetrics(**merged)


def evaluate_subject_on_split(
    labeled_table: pd.DataFrame,
    decision_column: str,
    split_name: str,
    probability_column: Optional[str] = None,
    probability_threshold: float = 0.5,
    probability_buckets: int = 10,
) -> tuple:
    """Returns (aggregate_metrics, breakdowns) for one subject (model or baseline) on one
    split ("train" | "validation" | "test") of an already `split`-labeled table.
    """
    split_rows = labeled_table[labeled_table["split"] == split_name]
    taken = split_rows[split_rows[decision_column]] if decision_column in split_rows.columns else split_rows.iloc[0:0]

    aggregate = compute_trade_metrics(taken)
    if probability_column and probability_column in split_rows.columns and not split_rows.empty:
        classification = compute_classification_metrics(split_rows, probability_column, probability_threshold)
        aggregate = _merge_metrics(aggregate, classification)

    breakdowns: List[EvaluationBreakdown] = []
    if not taken.empty:
        for symbol, group in taken.groupby("symbol"):
            breakdowns.append(
                EvaluationBreakdown(dimension="symbol", key=str(symbol), metrics=compute_trade_metrics(group))
            )
        for tf, group in taken.groupby("timeframe"):
            breakdowns.append(
                EvaluationBreakdown(dimension="timeframe", key=str(tf), metrics=compute_trade_metrics(group))
            )
        if "market_regime" in taken.columns:
            for regime, group in taken.groupby("market_regime"):
                if regime is None:
                    continue
                breakdowns.append(
                    EvaluationBreakdown(dimension="regime", key=str(regime), metrics=compute_trade_metrics(group))
                )
        if probability_column and probability_column in taken.columns:
            try:
                bucketed = pd.cut(taken[probability_column].astype(float), bins=probability_buckets)
                for interval, group in taken.groupby(bucketed, observed=True):
                    breakdowns.append(
                        EvaluationBreakdown(
                            dimension="probability_bucket", key=str(interval), metrics=compute_trade_metrics(group)
                        )
                    )
            except (ValueError, TypeError):
                pass

    return aggregate, breakdowns


def run_walk_forward_evaluation(
    subject_name: str,
    subject_type: str,
    fold_tables: List[pd.DataFrame],
    dataset_checksum: str,
    config_hash: str,
    decision_column: str,
    probability_column: Optional[str] = None,
    probability_buckets: int = 10,
    experiments_tried: int = 1,
    now: Optional[datetime] = None,
) -> EvaluationReport:
    """`fold_tables`: one already-`split`-labeled table per walk-forward fold (from
    packages.research.splits.assign_split_membership). Aggregates TEST-split results
    across all folds; also emits one "window" breakdown per fold so a strategy that only
    profits in a single fold is visible, not averaged away.
    """
    all_test_rows = []
    breakdowns: List[EvaluationBreakdown] = []

    for i, table in enumerate(fold_tables, start=1):
        if decision_column in table.columns:
            window_taken = table[(table["split"] == "test") & (table[decision_column])]
        else:
            window_taken = table.iloc[0:0]
        all_test_rows.append(table[table["split"] == "test"])
        breakdowns.append(
            EvaluationBreakdown(dimension="window", key=f"fold_{i}", metrics=compute_trade_metrics(window_taken))
        )

    combined_test = pd.concat(all_test_rows, ignore_index=True) if all_test_rows else pd.DataFrame()
    combined_test["split"] = "test"

    aggregate, extra_breakdowns = evaluate_subject_on_split(
        combined_test, decision_column, "test", probability_column, probability_buckets=probability_buckets
    )
    breakdowns.extend(extra_breakdowns)

    calibration_report = None
    if probability_column and probability_column in combined_test.columns:
        if decision_column in combined_test.columns:
            taken = combined_test[combined_test[decision_column]]
        else:
            taken = combined_test
        if not taken.empty:
            probs = taken[probability_column].astype(float).tolist()
            outcomes = (taken["label"] == "PROFIT").astype(int).tolist()
            try:
                scaler, method = fit_calibration(probs, outcomes, method="auto")
                calibration_report = build_calibration_report(scaler, method, probs, outcomes)
            except Exception:  # noqa: BLE001 - calibration is best-effort reporting, never blocks evaluation
                calibration_report = None

    multiple_testing_warning = None
    if experiments_tried > 20:
        multiple_testing_warning = (
            f"{experiments_tried} configurations were compared; results should be treated with "
            "increased skepticism for overfitting (see docs/ALPHA_EVIDENCE_POLICY.md)."
        )

    return EvaluationReport(
        subject_name=subject_name,
        subject_type=subject_type,
        dataset_checksum=dataset_checksum,
        walk_forward_windows=len(fold_tables),
        aggregate_metrics=aggregate,
        breakdowns=breakdowns,
        calibration=calibration_report,
        experiments_tried=experiments_tried,
        multiple_testing_warning=multiple_testing_warning,
        created_at=now or datetime.now(timezone.utc),
        code_commit=get_code_commit(),
        config_hash=config_hash,
    )
