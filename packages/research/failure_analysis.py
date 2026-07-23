"""Phase 1 — BTC/ETH Failure Analysis.

Reads the real, already-executed campaign artifacts (docs/research/experiments/
EXPERIMENT_LEDGER.csv, CANDIDATES.csv, GATE_RESULTS.csv) — does not re-run anything or
fabricate numbers — and produces a quantitative, per-(symbol, config) failure classification
plus supporting agent/regime/exit breakdowns.

Every classification threshold is declared as a module constant (not tuned after looking at
results) and documented in the generated report's methodology section.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENTS_DIR = REPO_ROOT / "docs" / "research" / "experiments"

# --- Classification thresholds (declared up front, not tuned post-hoc) ---
MIN_TRADE_COUNT = 20                    # matches PromotionGate.min_total_oos_trades
LOW_PROFIT_FACTOR_THRESHOLD = Decimal("1.0")   # breakeven; below this the strategy loses overall
NEGATIVE_SHARPE_THRESHOLD = Decimal("0.0")
HIGH_STOP_EXIT_RATIO = Decimal("0.90")  # >=90% of exits are stop-type (initial or trailing)
REGIME_CONCENTRATION_RATIO = Decimal("0.85")   # >=85% of trades (or of positive PnL) in one regime
MIN_AGENT_TRADES_FOR_ATTRIBUTION = Decimal("5")  # ignore agent buckets with <5 trades (noise floor)

STOP_EXIT_REASONS = {"INITIAL_STOP", "TRAILING_STOP"}


def _read_csv(path: Path) -> List[Dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def _d(value: str) -> Decimal:
    return Decimal(value) if value not in (None, "") else Decimal("0")


@dataclass
class ConfigSymbolAnalysis:
    symbol: str
    config_name: str
    total_oos_trades: int = 0
    win_rate: Optional[Decimal] = None
    gross_return_bps_sum: Decimal = Decimal("0")
    net_return_bps_sum: Decimal = Decimal("0")
    total_cost_bps_sum: Decimal = Decimal("0")
    expectancy_bps: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None
    mean_oos_sharpe: Optional[Decimal] = None
    worst_fold_drawdown_pct: Optional[Decimal] = None
    profitable_folds: int = 0
    total_folds: int = 0
    stop_exit_ratio: Optional[Decimal] = None
    take_profit_exit_ratio: Optional[Decimal] = None
    timeout_exit_ratio: str = "NOT_APPLICABLE"  # engine has no time-based exit mechanism
    avg_holding_days: Optional[Decimal] = None
    dominant_regime: Optional[str] = None
    dominant_regime_trade_ratio: Optional[Decimal] = None
    agent_breakdown: Dict[str, Dict] = field(default_factory=dict)  # agent -> {trades, net_return_bps_sum}
    negative_agents: List[str] = field(default_factory=list)
    gate_passed: bool = False
    gate_reasons: List[str] = field(default_factory=list)
    failure_reasons: List[str] = field(default_factory=list)


def analyze() -> List[ConfigSymbolAnalysis]:
    candidates = _read_csv(EXPERIMENTS_DIR / "CANDIDATES.csv")
    gate_rows = _read_csv(EXPERIMENTS_DIR / "GATE_RESULTS.csv")

    oos_closed = [
        c for c in candidates
        if c["run_type"] == "OOS_FOLD" and c["status"] == "CLOSED"
    ]

    gate_by_key = {(g["symbol"], g["config_name"]): g for g in gate_rows}

    grouped: Dict[tuple, List[Dict]] = defaultdict(list)
    for c in oos_closed:
        grouped[(c["symbol"], c["config_name"])].append(c)

    results: List[ConfigSymbolAnalysis] = []

    for (symbol, config_name), rows in grouped.items():
        a = ConfigSymbolAnalysis(symbol=symbol, config_name=config_name)
        a.total_oos_trades = len(rows)

        net_values = [_d(r["net_return_bps"]) for r in rows]
        gross_values = [_d(r["gross_return_bps"]) for r in rows]
        cost_values = [_d(r["total_cost_bps"]) for r in rows]

        wins = [r for r in rows if r["meta_label"] == "ACCEPT"]
        a.win_rate = (Decimal(len(wins)) / Decimal(len(rows)) * Decimal("100")) if rows else None

        a.gross_return_bps_sum = sum(gross_values, Decimal("0"))
        a.net_return_bps_sum = sum(net_values, Decimal("0"))
        a.total_cost_bps_sum = sum(cost_values, Decimal("0"))
        a.expectancy_bps = (a.net_return_bps_sum / len(rows)) if rows else None

        gross_profit = sum((v for v in net_values if v > 0), Decimal("0"))
        gross_loss = abs(sum((v for v in net_values if v < 0), Decimal("0")))
        a.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

        exit_counts = defaultdict(int)
        for r in rows:
            exit_counts[r["exit_reason"]] += 1
        stop_count = sum(v for k, v in exit_counts.items() if k in STOP_EXIT_REASONS)
        tp_count = exit_counts.get("TAKE_PROFIT", 0)
        a.stop_exit_ratio = (Decimal(stop_count) / Decimal(len(rows))) if rows else None
        a.take_profit_exit_ratio = (Decimal(tp_count) / Decimal(len(rows))) if rows else None

        from datetime import datetime
        holding_days = []
        for r in rows:
            if r["exit_timestamp"] and r["decision_timestamp"]:
                dt_exit = datetime.fromisoformat(r["exit_timestamp"])
                dt_dec = datetime.fromisoformat(r["decision_timestamp"])
                holding_days.append(Decimal((dt_exit - dt_dec).total_seconds()) / Decimal(86400))
        a.avg_holding_days = (sum(holding_days, Decimal("0")) / len(holding_days)) if holding_days else None

        regime_counts = defaultdict(int)
        for r in rows:
            regime_counts[r["market_regime"]] += 1
        if regime_counts:
            dom_regime, dom_count = max(regime_counts.items(), key=lambda kv: kv[1])
            a.dominant_regime = dom_regime
            a.dominant_regime_trade_ratio = Decimal(dom_count) / Decimal(len(rows))

        agent_net: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        agent_count: Dict[str, int] = defaultdict(int)
        for r in rows:
            agent_net[r["agent_source"]] += _d(r["net_return_bps"])
            agent_count[r["agent_source"]] += 1
        for agent, net in agent_net.items():
            a.agent_breakdown[agent] = {"trades": agent_count[agent], "net_return_bps_sum": str(net)}
            if agent_count[agent] >= MIN_AGENT_TRADES_FOR_ATTRIBUTION and net < 0:
                a.negative_agents.append(agent)

        gate_row = gate_by_key.get((symbol, config_name))
        if gate_row:
            a.gate_passed = gate_row["passed"] == "True"
            a.gate_reasons = [r for r in gate_row["reasons"].split(";") if r]
            a.mean_oos_sharpe = Decimal(gate_row["mean_oos_sharpe"]) if gate_row["mean_oos_sharpe"] else None
            a.worst_fold_drawdown_pct = (
                Decimal(gate_row["worst_fold_drawdown_pct"]) if gate_row["worst_fold_drawdown_pct"] else None
            )
            a.profitable_folds = int(gate_row["profitable_folds"])
            a.total_folds = int(gate_row["total_folds"])

        # --- Failure classification (mechanical, threshold-driven) ---
        reasons = []
        if a.total_oos_trades < MIN_TRADE_COUNT:
            reasons.append("LOW_TRADE_COUNT")
        if a.expectancy_bps is not None and a.expectancy_bps <= 0:
            reasons.append("NEGATIVE_EXPECTANCY")
        if a.mean_oos_sharpe is not None and a.mean_oos_sharpe < NEGATIVE_SHARPE_THRESHOLD:
            reasons.append("NEGATIVE_SHARPE")
        if a.profit_factor is not None and a.profit_factor < LOW_PROFIT_FACTOR_THRESHOLD:
            reasons.append("LOW_PROFIT_FACTOR")
        if a.gross_return_bps_sum > 0 and a.net_return_bps_sum <= 0:
            reasons.append("FEES_DOMINATE_EDGE")
        if a.stop_exit_ratio is not None and a.stop_exit_ratio >= HIGH_STOP_EXIT_RATIO:
            reasons.append("HIGH_STOP_LOSS_RATE")
        if a.dominant_regime_trade_ratio is not None and a.dominant_regime_trade_ratio >= REGIME_CONCENTRATION_RATIO:
            reasons.append("REGIME_DEPENDENCE")
        if a.total_folds > 0 and a.profitable_folds <= 1 and a.net_return_bps_sum > 0:
            reasons.append("SINGLE_FOLD_CONCENTRATION")
        if a.negative_agents:
            reasons.append("AGENT_SPECIFIC_LOSS")
        if not reasons and not a.gate_passed:
            reasons.append("INSUFFICIENT_GENERALIZATION")
        a.failure_reasons = reasons

        results.append(a)

    return sorted(results, key=lambda a: (a.config_name, a.symbol))


def write_outputs(results: List[ConfigSymbolAnalysis]) -> None:
    csv_path = EXPERIMENTS_DIR / "FAILURE_ANALYSIS.csv"
    fieldnames = [
        "symbol", "config_name", "total_oos_trades", "win_rate_pct", "gross_return_bps_sum",
        "net_return_bps_sum", "total_cost_bps_sum", "expectancy_bps", "profit_factor",
        "mean_oos_sharpe", "worst_fold_drawdown_pct", "profitable_folds", "total_folds",
        "stop_exit_ratio", "take_profit_exit_ratio", "timeout_exit_ratio", "avg_holding_days",
        "dominant_regime", "dominant_regime_trade_ratio", "negative_agents", "gate_passed",
        "gate_reasons", "failure_reasons",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for a in results:
            writer.writerow({
                "symbol": a.symbol,
                "config_name": a.config_name,
                "total_oos_trades": a.total_oos_trades,
                "win_rate_pct": a.win_rate,
                "gross_return_bps_sum": a.gross_return_bps_sum,
                "net_return_bps_sum": a.net_return_bps_sum,
                "total_cost_bps_sum": a.total_cost_bps_sum,
                "expectancy_bps": a.expectancy_bps,
                "profit_factor": a.profit_factor,
                "mean_oos_sharpe": a.mean_oos_sharpe,
                "worst_fold_drawdown_pct": a.worst_fold_drawdown_pct,
                "profitable_folds": a.profitable_folds,
                "total_folds": a.total_folds,
                "stop_exit_ratio": a.stop_exit_ratio,
                "take_profit_exit_ratio": a.take_profit_exit_ratio,
                "timeout_exit_ratio": a.timeout_exit_ratio,
                "avg_holding_days": a.avg_holding_days,
                "dominant_regime": a.dominant_regime,
                "dominant_regime_trade_ratio": a.dominant_regime_trade_ratio,
                "negative_agents": "|".join(a.negative_agents),
                "gate_passed": a.gate_passed,
                "gate_reasons": ";".join(a.gate_reasons),
                "failure_reasons": ";".join(a.failure_reasons),
            })
    print(f"[failure_analysis] wrote {csv_path} ({len(results)} rows)")


if __name__ == "__main__":
    res = analyze()
    write_outputs(res)
