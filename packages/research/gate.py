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
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional


@dataclass(frozen=True)
class PromotionGate:
    min_total_oos_trades: int = 20
    min_profitable_fold_ratio: Decimal = Decimal("0.66")  # >= 2 of 3 folds net-positive
    min_mean_oos_sharpe: Decimal = Decimal("0.5")
    max_worst_fold_drawdown_pct: Decimal = Decimal("25.0")
    require_positive_aggregate_pnl: bool = True
    require_every_fold_populated: bool = True


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


def evaluate_gate(
    symbol: str,
    config_name: str,
    config_hash: str,
    fold_results: List[FoldResult],
    gate: PromotionGate = PromotionGate(),
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
