"""The Alpha Research Campaign's promotion gate.

This is the ONLY mechanism allowed to mark a (symbol, config) pair as evidence-worthy.
Every criterion here is evaluated purely on out-of-sample (walk-forward test-fold) results
produced by the real, production `EventDrivenBacktestEngine` / `DecisionService` pipeline —
never on in-sample/training-window numbers, and never fabricated. A config that fails any
criterion is recorded in the experiment ledger like every other run, but is NOT written into
the published evidence document.

Thresholds are deliberately conservative and documented (see docs/research/
ALPHA_RESEARCH_GATE.md) rather than tuned post-hoc to whatever the campaign happens to
produce — that would defeat the purpose of having a gate.

`apply_overfitting_controls` is a SEPARATE, second layer on top of `evaluate_gate`'s
fixed-threshold criteria: it never turns a failed gate into a passed one, only the reverse
(downgrade-only, same policy `packages.research.evidence_publisher` uses on the
feat/alpha-dataset-training lineage this reconciles). `evaluate_gate` itself is intentionally
left unmodified — it is single-trial-scoped and has no visibility into how many other configs
were tried, which is exactly what a multiple-testing correction needs; that context only
exists one level up, at the campaign's per-symbol config-grid loop.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import pstdev
from typing import Dict, List, Optional

from packages.research.exceptions import InsufficientDataError
from packages.research.overfitting import compute_pbo, deflated_sharpe_ratio, performance_matrix_from_window_breakdowns

# Bump this whenever PromotionGate's thresholds or evaluation logic change. Evidence records
# bind to the exact gate_version that produced them (packages/evidence/models.py) — a config
# approved under gate_v1 says nothing about whether it would clear gate_v2.
GATE_VERSION = "gate_v1"


@dataclass(frozen=True)
class PromotionGate:
    min_total_oos_trades: int = 20
    min_profitable_fold_ratio: Decimal = Decimal("0.66")  # >= 2 of 3 folds net-positive
    min_mean_oos_sharpe: Decimal = Decimal("0.5")
    max_worst_fold_drawdown_pct: Decimal = Decimal("25.0")
    require_positive_aggregate_pnl: bool = True
    require_every_fold_populated: bool = True
    # Second-layer overfitting controls (see apply_overfitting_controls below). DSR asks
    # "how likely is the true Sharpe positive, after accounting for how many configs were
    # tried" — min 0.95 means "at least 95% probability", a conservative bar appropriate for
    # a config-grid search where dozens of variants may have been tried per symbol.
    min_deflated_sharpe_ratio: Decimal = Decimal("0.95")
    max_probability_of_backtest_overfitting: Decimal = Decimal("0.5")


@dataclass
class FoldResult:
    fold_number: int
    test_start: str
    test_end: str
    trades: int
    net_profit: Decimal
    total_return_pct: Decimal
    sharpe_ratio: Optional[Decimal]
    max_drawdown_pct: Decimal


@dataclass
class GateResult:
    symbol: str
    config_name: str
    config_hash: str
    passed: bool
    reasons: List[str] = field(default_factory=list)
    total_oos_trades: int = 0
    profitable_folds: int = 0
    total_folds: int = 0
    mean_oos_sharpe: Optional[Decimal] = None
    worst_fold_drawdown_pct: Optional[Decimal] = None
    aggregate_net_profit: Optional[Decimal] = None
    # Populated only by apply_overfitting_controls (None means "not yet evaluated", not
    # "passed with no overfitting concern").
    deflated_sharpe_ratio: Optional[Decimal] = None
    probability_of_backtest_overfitting: Optional[Decimal] = None
    multiple_testing_warning: Optional[str] = None


DEFAULT_GATE = PromotionGate()


def evaluate_gate(
    symbol: str,
    config_name: str,
    config_hash: str,
    fold_results: List[FoldResult],
    gate: PromotionGate = DEFAULT_GATE,
) -> GateResult:
    reasons: List[str] = []

    total_folds = len(fold_results)
    total_oos_trades = sum(f.trades for f in fold_results)
    profitable_folds = sum(1 for f in fold_results if f.net_profit > Decimal("0"))
    aggregate_net_profit = sum((f.net_profit for f in fold_results), Decimal("0"))

    sharpe_values = [f.sharpe_ratio for f in fold_results if f.sharpe_ratio is not None]
    mean_oos_sharpe = (sum(sharpe_values) / len(sharpe_values)) if sharpe_values else None

    worst_fold_drawdown_pct = max((f.max_drawdown_pct for f in fold_results), default=None)

    if gate.require_every_fold_populated:
        empty_folds = [f.fold_number for f in fold_results if f.trades == 0]
        if empty_folds:
            reasons.append(f"INSUFFICIENT_SAMPLE_IN_FOLDS:{empty_folds}")

    if total_oos_trades < gate.min_total_oos_trades:
        reasons.append(
            f"TOTAL_OOS_TRADES_BELOW_MIN:{total_oos_trades}<{gate.min_total_oos_trades}"
        )

    if total_folds > 0:
        profitable_ratio = Decimal(profitable_folds) / Decimal(total_folds)
        if profitable_ratio < gate.min_profitable_fold_ratio:
            reasons.append(
                f"PROFITABLE_FOLD_RATIO_BELOW_MIN:{profitable_folds}/{total_folds}"
            )
    else:
        reasons.append("NO_FOLDS_EVALUATED")

    if mean_oos_sharpe is None or mean_oos_sharpe < gate.min_mean_oos_sharpe:
        reasons.append(f"MEAN_OOS_SHARPE_BELOW_MIN:{mean_oos_sharpe}<{gate.min_mean_oos_sharpe}")

    if worst_fold_drawdown_pct is None or worst_fold_drawdown_pct > gate.max_worst_fold_drawdown_pct:
        reasons.append(
            f"WORST_FOLD_DRAWDOWN_ABOVE_MAX:{worst_fold_drawdown_pct}>{gate.max_worst_fold_drawdown_pct}"
        )

    if gate.require_positive_aggregate_pnl and aggregate_net_profit <= Decimal("0"):
        reasons.append(f"AGGREGATE_NET_PNL_NOT_POSITIVE:{aggregate_net_profit}")

    return GateResult(
        symbol=symbol,
        config_name=config_name,
        config_hash=config_hash,
        passed=len(reasons) == 0,
        reasons=reasons,
        total_oos_trades=total_oos_trades,
        profitable_folds=profitable_folds,
        total_folds=total_folds,
        mean_oos_sharpe=mean_oos_sharpe,
        worst_fold_drawdown_pct=worst_fold_drawdown_pct,
        aggregate_net_profit=aggregate_net_profit,
    )


def apply_overfitting_controls(
    gate_results: List[GateResult],
    fold_sharpes_by_trial: Dict[str, List[Optional[float]]],
    gate: PromotionGate = DEFAULT_GATE,
) -> List[GateResult]:
    """Second layer, downgrade-only: multiple-testing correction across every (symbol,
    config) trial evaluated for ONE symbol in a campaign.

    `gate_results`: every GateResult for that symbol (config_name identifies each trial).
    `fold_sharpes_by_trial`: {config_name: [sharpe_fold_1, sharpe_fold_2, ...]} for the SAME
    set of trials — the cross-trial context `evaluate_gate` itself cannot see (it only
    receives one trial's own fold results). A missing per-fold Sharpe (no trades that fold)
    is treated as 0.0, matching `performance_matrix_from_window_breakdowns`'s convention.

    Never turns a failed base-gate result into a passed one — only ever adds a reason and/or
    flips `passed=True` to `passed=False`.
    """
    n_trials = len(fold_sharpes_by_trial)
    if n_trials == 0:
        return gate_results

    trial_mean_sharpes = []
    for sharpes in fold_sharpes_by_trial.values():
        observed = [v for v in sharpes if v is not None]
        trial_mean_sharpes.append(sum(observed) / len(observed) if observed else 0.0)
    trial_sharpe_std = pstdev(trial_mean_sharpes) if len(trial_mean_sharpes) > 1 else 1.0

    multiple_testing_warning = None
    if n_trials > 20:
        multiple_testing_warning = (
            f"{n_trials} configurations were compared for this symbol; results should be "
            "treated with increased skepticism for overfitting (see docs/research/ALPHA_RESEARCH_GATE.md)."
        )

    pbo: Optional[Decimal] = None
    try:
        matrix = performance_matrix_from_window_breakdowns(fold_sharpes_by_trial)
        if matrix.shape[0] >= 2 and matrix.shape[1] >= 2:
            pbo = Decimal(str(round(compute_pbo(matrix), 6)))
    except InsufficientDataError:
        pbo = None  # too few trials/folds to estimate — not an error, just not computable yet

    updated: List[GateResult] = []
    for g in gate_results:
        reasons = list(g.reasons)
        passed = g.passed
        dsr: Optional[Decimal] = None

        if g.mean_oos_sharpe is not None and g.total_oos_trades > 1:
            try:
                dsr_value = deflated_sharpe_ratio(
                    observed_sharpe=float(g.mean_oos_sharpe), n_trials=n_trials,
                    n_observations=g.total_oos_trades, trial_sharpe_std=trial_sharpe_std,
                )
                dsr = Decimal(str(round(dsr_value, 6)))
            except InsufficientDataError:
                dsr = None

        if dsr is not None and dsr < gate.min_deflated_sharpe_ratio:
            reasons.append(f"DEFLATED_SHARPE_RATIO_BELOW_MIN:{dsr}<{gate.min_deflated_sharpe_ratio}")
            passed = False

        if pbo is not None and pbo > gate.max_probability_of_backtest_overfitting:
            reasons.append(
                f"PROBABILITY_OF_BACKTEST_OVERFITTING_ABOVE_MAX:{pbo}>{gate.max_probability_of_backtest_overfitting}"
            )
            passed = False

        updated.append(
            GateResult(
                symbol=g.symbol, config_name=g.config_name, config_hash=g.config_hash, passed=passed,
                reasons=reasons, total_oos_trades=g.total_oos_trades, profitable_folds=g.profitable_folds,
                total_folds=g.total_folds, mean_oos_sharpe=g.mean_oos_sharpe,
                worst_fold_drawdown_pct=g.worst_fold_drawdown_pct, aggregate_net_profit=g.aggregate_net_profit,
                deflated_sharpe_ratio=dsr, probability_of_backtest_overfitting=pbo,
                multiple_testing_warning=multiple_testing_warning,
            )
        )
    return updated
