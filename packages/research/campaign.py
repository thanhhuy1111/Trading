"""Full Alpha Research Campaign orchestrator.

Runs the curated model-configuration grid (`config_grid.py`) against real, multi-year
Binance daily candles (`data_fetcher.py`) through the exact production
`EventDrivenBacktestEngine` / `DecisionService` pipeline — the same code path paper trading
uses, so nothing here is a fabricated or shortcut simulation.

Every single experiment (pass or fail) is appended to the experiment ledger. Only
(symbol, config) pairs that clear `gate.evaluate_gate` on out-of-sample walk-forward test
folds, on every symbol tested, are written into the published evidence document.

Scale strategy:
  - `packages/backtest/engine.py` was fixed to use a bounded feature-lookback window and a
    single asyncio event loop per session (was O(n^2) with per-candle loop churn).
  - Experiments are independent (symbol, config, fold) triples, so they're distributed across
    a `ProcessPoolExecutor` — real horizontal scale-out, not just an in-process loop.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from packages.market_data.models import Timeframe

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "docs" / "research" / "experiments"

SYMBOLS = ["BTC/USDT", "ETH/USDT"]
TIMEFRAME = Timeframe.D1
NUM_FOLDS = 3
WARMUP_CALENDAR_DAYS = 300  # >= FEATURE_LOOKBACK_WINDOW (250 daily candles) with safety margin
PURGE_HOURS = 24 * 7
EMBARGO_HOURS = 24 * 7
INITIAL_CASH = Decimal("100000.00")
RANDOM_SEED = 42


def _candidate_to_row(candidate, task: Dict, session_id) -> Dict:
    """Flattens a TradeCandidate into a CSV-safe row, tagged with the experiment it came
    from so trade-level records can always be traced back to (symbol, config, fold)."""
    return {
        "session_id": str(session_id),
        "symbol": task["symbol"],
        "config_name": task["config_name"],
        "run_type": task["run_type"],
        "fold_number": task.get("fold_number") or "",
        "candidate_id": str(candidate.candidate_id),
        "status": candidate.status.value,
        "decision_timestamp": candidate.decision_timestamp.isoformat(),
        "agent_source": candidate.agent_source,
        "agent_confidence": str(candidate.agent_confidence),
        "supporting_agents": "|".join(candidate.supporting_agents),
        "opposing_agents": "|".join(candidate.opposing_agents),
        "consensus_score": str(candidate.consensus_score),
        "market_regime": candidate.market_regime,
        "entry_reference": str(candidate.entry_reference),
        "actual_entry_price": str(candidate.actual_entry_price) if candidate.actual_entry_price is not None else "",
        "stop_loss": str(candidate.stop_loss) if candidate.stop_loss is not None else "",
        "take_profit": str(candidate.take_profit) if candidate.take_profit is not None else "",
        "risk_reward_ratio": str(candidate.risk_reward_ratio) if candidate.risk_reward_ratio is not None else "",
        "estimated_fee_bps": str(candidate.estimated_fee_bps),
        "estimated_spread_bps": str(candidate.estimated_spread_bps),
        "estimated_slippage_bps": str(candidate.estimated_slippage_bps),
        "risk_rejection_reasons": "|".join(candidate.risk_rejection_reasons),
        "exit_timestamp": candidate.exit_timestamp.isoformat() if candidate.exit_timestamp else "",
        "exit_price": str(candidate.exit_price) if candidate.exit_price is not None else "",
        "exit_reason": candidate.exit_reason or "",
        "gross_return_bps": str(candidate.gross_return_bps) if candidate.gross_return_bps is not None else "",
        "total_cost_bps": str(candidate.total_cost_bps) if candidate.total_cost_bps is not None else "",
        "net_return_bps": str(candidate.net_return_bps) if candidate.net_return_bps is not None else "",
        "meta_label": candidate.meta_label or "",
        "strategy_config_hash": candidate.strategy_config_hash,
    }


def _run_single_experiment(task: Dict) -> Dict:
    """Runs exactly one backtest session. Must stay import-light and self-contained so it
    pickles cleanly for ProcessPoolExecutor. Any failure is captured and returned as a row
    rather than raised, so one bad experiment can't take down the whole campaign."""
    from packages.backtest.datasets import dataset_registry
    from packages.backtest.engine import EventDrivenBacktestEngine
    from packages.backtest.models import BacktestConfig, BacktestMode
    from packages.research.config_grid import build_strategy_config
    from packages.research.data_fetcher import load_or_fetch

    result = dict(task)
    result["status"] = "ERROR"
    result["error"] = ""
    result["candidates"] = []

    try:
        symbol = task["symbol"]
        test_start = datetime.fromisoformat(task["test_start"])
        test_end = datetime.fromisoformat(task["test_end"])
        warmup_start = datetime.fromisoformat(task["warmup_start"])
        global_start = datetime.fromisoformat(task["global_start"])
        global_end = datetime.fromisoformat(task["global_end"])

        candles = load_or_fetch(symbol, TIMEFRAME, global_start, global_end, force_refresh=False)
        sliced = [c for c in candles if warmup_start <= c.close_time <= test_end]
        if not sliced:
            result["error"] = "EMPTY_SLICE"
            return result

        dataset = dataset_registry.register_dataset(
            name=f"{symbol}_{task['run_type']}_{task.get('fold_number', 'FULL')}_{uuid4().hex[:6]}",
            symbols=[symbol],
            timeframes=[TIMEFRAME.value],
            candles=sliced,
        )

        strategy_config = build_strategy_config(task["overrides"])
        fold_number = task.get("fold_number") or None
        if fold_number is not None:
            fold_number = int(fold_number)

        cfg = BacktestConfig(
            session_name=task["config_name"],
            mode=BacktestMode.HISTORICAL_REPLAY,
            dataset_id=dataset.dataset_id,
            symbols=[symbol],
            timeframes=[TIMEFRAME.value],
            start_time=test_start,
            end_time=test_end,
            warmup_start_time=warmup_start,
            initial_cash=INITIAL_CASH,
            random_seed=RANDOM_SEED,
            strategy_config=strategy_config,
            fold_number=fold_number,
        )

        engine = EventDrivenBacktestEngine()
        session = engine.create_session(cfg)
        report = engine.run_backtest(session.session_id)
        candidates = engine.get_candidates(session.session_id)
        result["candidates"] = [_candidate_to_row(c, task, session.session_id) for c in candidates]

        m = report.metrics
        result.update({
            "status": "OK",
            "dataset_checksum": report.dataset_checksum,
            "reproducibility_fingerprint": report.reproducibility_fingerprint,
            "config_hash": strategy_config.config_hash,
            "trades": report.trade_count,
            "net_profit": str(m.net_profit),
            "total_return_pct": str(m.total_return_pct),
            "annualized_return_pct": str(m.annualized_return_pct) if m.annualized_return_pct is not None else "",
            "sharpe_ratio": str(m.sharpe_ratio) if m.sharpe_ratio is not None else "",
            "sortino_ratio": str(m.sortino_ratio) if m.sortino_ratio is not None else "",
            "calmar_ratio": str(m.calmar_ratio) if m.calmar_ratio is not None else "",
            "max_drawdown_pct": str(m.max_drawdown_pct),
            "win_rate": str(m.win_rate),
            "profit_factor": str(m.profit_factor) if m.profit_factor is not None else "",
            "total_fees": str(m.total_fees),
            "final_nav": str(m.final_nav),
        })
    except Exception as exc:  # noqa: BLE001 - deliberately broad: one row must never crash the pool
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def _build_tasks(global_start: datetime, global_end: datetime) -> List[Dict]:
    from packages.backtest.walk_forward import walk_forward_runner
    from packages.research.config_grid import iter_variants

    tasks: List[Dict] = []
    variants = list(iter_variants())

    for symbol in SYMBOLS:
        folds = walk_forward_runner.generate_folds(
            session_id=uuid4(),
            start_time=global_start,
            end_time=global_end,
            num_folds=NUM_FOLDS,
            purge_hours=PURGE_HOURS,
            embargo_hours=EMBARGO_HOURS,
        )

        for config_name, rationale, overrides in variants:
            # Out-of-sample walk-forward folds — these feed the promotion gate.
            for fold in folds:
                warmup_start = max(global_start, fold.test_start - timedelta(days=WARMUP_CALENDAR_DAYS))
                tasks.append({
                    "run_id": uuid4().hex,
                    "symbol": symbol,
                    "config_name": config_name,
                    "rationale": rationale,
                    "overrides": overrides,
                    "run_type": "OOS_FOLD",
                    "fold_number": fold.fold_number,
                    "test_start": fold.test_start.isoformat(),
                    "test_end": fold.test_end.isoformat(),
                    "warmup_start": warmup_start.isoformat(),
                    "global_start": global_start.isoformat(),
                    "global_end": global_end.isoformat(),
                })

            # Full-period descriptive run — NOT used for gating (in-sample over the whole
            # history), kept only for transparency/context in the ledger.
            tasks.append({
                "run_id": uuid4().hex,
                "symbol": symbol,
                "config_name": config_name,
                "rationale": rationale,
                "overrides": overrides,
                "run_type": "FULL_PERIOD",
                "fold_number": "",
                "test_start": global_start.isoformat(),
                "test_end": global_end.isoformat(),
                "warmup_start": global_start.isoformat(),
                "global_start": global_start.isoformat(),
                "global_end": global_end.isoformat(),
            })

    return tasks


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "UNKNOWN"


def run_campaign(max_workers: Optional[int] = None) -> Dict:
    from packages.research.data_fetcher import load_or_fetch

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * 7 + 200)

    # Pre-fetch/cache real candles from the main process before fan-out so worker
    # processes only ever read the local cache (no concurrent network races).
    per_symbol_span = {}
    for symbol in SYMBOLS:
        candles = load_or_fetch(symbol, TIMEFRAME, start, end, force_refresh=False)
        per_symbol_span[symbol] = (candles[0].close_time, candles[-1].close_time)

    global_start = max(span[0] for span in per_symbol_span.values())
    global_end = min(span[1] for span in per_symbol_span.values())

    tasks = _build_tasks(global_start, global_end)
    worker_count = max_workers or min(4, os.cpu_count() or 1)

    print(f"[campaign] {len(tasks)} experiments queued across {worker_count} worker processes")
    t0 = time.time()

    results: List[Dict] = []
    with ProcessPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(_run_single_experiment, task): task for task in tasks}
        completed = 0
        for future in as_completed(futures):
            results.append(future.result())
            completed += 1
            if completed % 20 == 0 or completed == len(tasks):
                print(f"[campaign] {completed}/{len(tasks)} experiments completed "
                      f"({time.time() - t0:.1f}s elapsed)")

    elapsed = time.time() - t0
    print(f"[campaign] all {len(results)} experiments completed in {elapsed:.1f}s")

    _write_ledger(results)
    _write_candidates(results)
    gate_results = _evaluate_and_write_gate(results)
    manifest = _write_manifest(results, gate_results, elapsed, global_start, global_end, worker_count)
    _write_evidence(gate_results, results)

    return manifest


def _write_ledger(results: List[Dict]) -> None:
    path = EVIDENCE_DIR / "EXPERIMENT_LEDGER.csv"
    fieldnames = [
        "run_id", "symbol", "config_name", "run_type", "fold_number", "status", "error",
        "config_hash", "dataset_checksum", "reproducibility_fingerprint",
        "test_start", "test_end", "trades", "net_profit", "total_return_pct",
        "annualized_return_pct", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
        "max_drawdown_pct", "win_rate", "profit_factor", "total_fees", "final_nav", "rationale",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(results, key=lambda r: (r["symbol"], r["config_name"], r["run_type"], str(r["fold_number"]))):
            writer.writerow(row)
    print(f"[campaign] full experiment ledger written: {path} ({len(results)} rows)")


def _write_candidates(results: List[Dict]) -> None:
    path = EVIDENCE_DIR / "CANDIDATES.csv"
    fieldnames = [
        "session_id", "symbol", "config_name", "run_type", "fold_number", "candidate_id", "status",
        "decision_timestamp", "agent_source", "agent_confidence", "supporting_agents", "opposing_agents",
        "consensus_score", "market_regime", "entry_reference", "actual_entry_price", "stop_loss",
        "take_profit", "risk_reward_ratio", "estimated_fee_bps", "estimated_spread_bps",
        "estimated_slippage_bps", "risk_rejection_reasons", "exit_timestamp", "exit_price", "exit_reason",
        "gross_return_bps", "total_cost_bps", "net_return_bps", "meta_label", "strategy_config_hash",
    ]
    all_rows = [row for r in results for row in r.get("candidates", [])]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(all_rows, key=lambda r: (r["symbol"], r["config_name"], r["run_type"], str(r["fold_number"]), r["decision_timestamp"])):
            writer.writerow(row)
    print(f"[campaign] full candidate lineage written: {path} ({len(all_rows)} rows)")


def _evaluate_and_write_gate(results: List[Dict]):
    from packages.research.gate import FoldResult, PromotionGate, evaluate_gate

    oos_rows = [r for r in results if r["run_type"] == "OOS_FOLD" and r["status"] == "OK"]

    grouped: Dict[tuple, List[Dict]] = {}
    for row in oos_rows:
        key = (row["symbol"], row["config_name"])
        grouped.setdefault(key, []).append(row)

    gate = PromotionGate()
    gate_results = []
    for (symbol, config_name), rows in grouped.items():
        fold_results = [
            FoldResult(
                fold_number=int(r["fold_number"]),
                test_start=r["test_start"],
                test_end=r["test_end"],
                trades=int(r["trades"]),
                net_profit=Decimal(r["net_profit"]),
                total_return_pct=Decimal(r["total_return_pct"]),
                sharpe_ratio=Decimal(r["sharpe_ratio"]) if r["sharpe_ratio"] else None,
                max_drawdown_pct=Decimal(r["max_drawdown_pct"]),
            )
            for r in rows
        ]
        config_hash = rows[0]["config_hash"]
        gate_results.append(evaluate_gate(symbol, config_name, config_hash, fold_results, gate))

    path = EVIDENCE_DIR / "GATE_RESULTS.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "symbol", "config_name", "config_hash", "passed", "reasons",
            "total_oos_trades", "profitable_folds", "total_folds",
            "mean_oos_sharpe", "worst_fold_drawdown_pct", "aggregate_net_profit",
        ])
        for g in sorted(gate_results, key=lambda g: (g.config_name, g.symbol)):
            writer.writerow([
                g.symbol, g.config_name, g.config_hash, g.passed, ";".join(g.reasons),
                g.total_oos_trades, g.profitable_folds, g.total_folds,
                g.mean_oos_sharpe, g.worst_fold_drawdown_pct, g.aggregate_net_profit,
            ])
    print(f"[campaign] gate evaluation written: {path} ({len(gate_results)} (symbol,config) pairs)")
    return gate_results


def _write_manifest(results, gate_results, elapsed, global_start, global_end, worker_count) -> Dict:
    ok = [r for r in results if r["status"] == "OK"]
    errored = [r for r in results if r["status"] != "OK"]
    passed_per_symbol = [g for g in gate_results if g.passed]

    config_names = {r["config_name"] for r in results}
    per_config_symbols_passed: Dict[str, set] = {}
    for g in passed_per_symbol:
        per_config_symbols_passed.setdefault(g.config_name, set()).add(g.symbol)
    promoted = sorted([c for c, syms in per_config_symbols_passed.items() if syms == set(SYMBOLS)])

    manifest = {
        "campaign": "full_alpha_research_campaign",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "symbols": SYMBOLS,
        "timeframe": TIMEFRAME.value,
        "num_configs": len(config_names),
        "num_folds": NUM_FOLDS,
        "data_range": {"start": global_start.isoformat(), "end": global_end.isoformat()},
        "worker_processes": worker_count,
        "elapsed_seconds": round(elapsed, 2),
        "total_experiments": len(results),
        "experiments_ok": len(ok),
        "experiments_errored": len(errored),
        "symbol_config_pairs_evaluated": len(gate_results),
        "symbol_config_pairs_passed_gate": len(passed_per_symbol),
        "configs_promoted_all_symbols": promoted,
    }
    path = EVIDENCE_DIR / "CAMPAIGN_MANIFEST.json"
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[campaign] manifest written: {path}")
    print(json.dumps(manifest, indent=2))
    return manifest


def _write_evidence(gate_results, results) -> None:
    from packages.research.config_grid import CONFIG_GRID

    passed = [g for g in gate_results if g.passed]
    per_config_symbols_passed: Dict[str, set] = {}
    for g in passed:
        per_config_symbols_passed.setdefault(g.config_name, set()).add(g.symbol)
    promoted = sorted([c for c, syms in per_config_symbols_passed.items() if syms == set(SYMBOLS)])

    out_path = REPO_ROOT / "docs" / "research" / "ALPHA_RESEARCH_CAMPAIGN_EVIDENCE.md"
    lines = ["# Full Alpha Research Campaign — Evidence Report", ""]
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()} | git: {_git_sha()}_")
    lines.append("")
    lines.append(
        "This report is generated exclusively from real out-of-sample walk-forward results "
        "produced by `packages/research/campaign.py` running the production "
        "`EventDrivenBacktestEngine`. See `docs/research/ALPHA_RESEARCH_GATE.md` for the exact "
        "promotion-gate criteria and `docs/research/experiments/` for the full, unfiltered "
        "experiment ledger (every run, pass or fail)."
    )
    lines.append("")

    if not promoted:
        lines.append("## Result: NO STRATEGY CONFIGURATION CLEARED THE GATE")
        lines.append("")
        lines.append(
            "No (symbol, config) pair in this campaign passed the promotion gate on **both** "
            "BTC/USDT and ETH/USDT out-of-sample walk-forward folds. Per campaign policy, "
            "**no strategy evidence is published** — this section exists precisely to avoid "
            "publishing evidence for something that did not actually clear the gate."
        )
        lines.append("")
        lines.append("### Closest near-misses (for context only — NOT promoted, NOT for paper/live use)")
        lines.append("")
        near = sorted(
            [g for g in gate_results],
            key=lambda g: (g.mean_oos_sharpe if g.mean_oos_sharpe is not None else Decimal("-999")),
            reverse=True,
        )[:10]
        lines.append("| Symbol | Config | Passed | Reasons | OOS Trades | Profitable Folds | Mean OOS Sharpe | Worst Fold DD % | Aggregate Net PnL |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for g in near:
            lines.append(
                f"| {g.symbol} | {g.config_name} | {g.passed} | {'; '.join(g.reasons) or '-'} | "
                f"{g.total_oos_trades} | {g.profitable_folds}/{g.total_folds} | {g.mean_oos_sharpe} | "
                f"{g.worst_fold_drawdown_pct} | {g.aggregate_net_profit} |"
            )
        lines.append("")
    else:
        lines.append("## Result: PROMOTED CONFIGURATIONS")
        lines.append("")
        lines.append(
            f"{len(promoted)} configuration(s) cleared the promotion gate on out-of-sample "
            "walk-forward folds for every symbol tested (BTC/USDT and ETH/USDT):"
        )
        lines.append("")
        for config_name in promoted:
            rationale = CONFIG_GRID[config_name][0]
            lines.append(f"### `{config_name}`")
            lines.append("")
            lines.append(f"**Hypothesis:** {rationale}")
            lines.append("")
            lines.append("| Symbol | Config Hash | OOS Trades | Profitable Folds | Mean OOS Sharpe | Worst Fold DD % | Aggregate Net PnL | Reproducibility Fingerprint (fold 1) |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for g in [g for g in passed if g.config_name == config_name]:
                fp_row = next(
                    (r for r in results if r["config_name"] == config_name and r["symbol"] == g.symbol
                     and r["run_type"] == "OOS_FOLD" and str(r.get("fold_number")) == "1"),
                    {},
                )
                lines.append(
                    f"| {g.symbol} | `{g.config_hash[:16]}` | {g.total_oos_trades} | "
                    f"{g.profitable_folds}/{g.total_folds} | {g.mean_oos_sharpe} | "
                    f"{g.worst_fold_drawdown_pct} | {g.aggregate_net_profit} | "
                    f"`{fp_row.get('reproducibility_fingerprint', 'N/A')}` |"
                )
            lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[campaign] evidence report written: {out_path}")


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_campaign(max_workers=workers)
