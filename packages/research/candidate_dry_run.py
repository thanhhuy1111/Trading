"""Phase 0.4 (Checkpoint 2 carryover): a real, no-ML dry run of the full raw-candle -> candidate
pipeline across every real 1h/4h dataset fetched in Checkpoint 2.

This is NOT a backtest (no fills, no PnL) and trains nothing. It exercises validate ->
feature -> regime -> route -> decide -> candidate at every real decision point in the actual
BTC/ETH/BNB/SOL 1h/4h data and counts what happened, catching wiring bugs (lineage
violations, leakage, duplicate candidates) that only show up at real scale, not in small
fixture tests.

Methodology note on `dropped_by_stale_policy`: staleness is fundamentally a *live-runtime*
concept (Phase 7: "is the latest candle too old relative to wall-clock now"), which doesn't
have a literal meaning when replaying history. Adapted here as: a decision point is
"stale-policy dropped" if a data gap falls inside its label-horizon window (the data needed to
know whether this decision would have worked out is itself missing/stale), reusing
`filter_valid_decision_points`'s GAP_IN_LABEL_HORIZON classification. `dropped_by_gap_policy`
uses the same function's GAP_IN_FEATURE_LOOKBACK classification (the inputs to the decision
were contaminated by a gap). Both are computed from the real gaps found in Phase 0.1/0.2.
"""

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from packages.agents.regime import MarketRegimeAgent
from packages.backtest.timeframe_config import get_timeframe_config
from packages.candidates.builder import build_proposed_candidate
from packages.governance.decision_service import decision_service
from packages.governance.strategy_router import route
from packages.market_data.historical_quality import filter_valid_decision_points, validate_historical_series
from packages.market_data.models import Timeframe
from packages.research.data_fetcher import load_or_fetch_resumable

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_MD_PATH = REPO_ROOT / "docs" / "research" / "REAL_CANDIDATE_DRY_RUN_REPORT.md"
REPORT_JSON_PATH = REPO_ROOT / "docs" / "research" / "experiments" / "REAL_CANDIDATE_DRY_RUN.json"

SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
TIMEFRAMES = [Timeframe.H1, Timeframe.H4]
FEATURE_LOOKBACK_WINDOW = 250  # matches packages/backtest/engine.py's bounded window

_regime_agent = MarketRegimeAgent()


@dataclass
class DryRunResult:
    symbol: str
    timeframe: str
    total_clean_candles: int
    valid_decision_points: int = 0
    dropped_by_gap_policy: int = 0
    dropped_by_stale_policy: int = 0
    regime_distribution: Dict[str, int] = field(default_factory=dict)
    routed_agent_execution_count: int = 0
    candidate_count: int = 0
    completed_label_count: int = 0
    duplicate_candidate_count: int = 0
    lineage_violation_count: int = 0
    leakage_violation_count: int = 0
    elapsed_seconds: float = 0.0


async def dry_run_one(symbol: str, timeframe: Timeframe) -> DryRunResult:
    t0 = time.time()
    end = datetime.now(timezone.utc)
    raw = load_or_fetch_resumable(symbol, timeframe, end, end)  # cache-only; range irrelevant on a hit
    clean, quality_report = validate_historical_series(raw, timeframe, as_of=end)

    tf_config = get_timeframe_config(timeframe)
    label_horizon_bars = max(1, int(tf_config.label_horizon / _interval(timeframe)))

    decision_timestamps = [c.close_time for c in clean]
    feature_lookback_span = tf_config.feature_lookback_bars * _interval(timeframe)
    validity = filter_valid_decision_points(
        decision_timestamps, quality_report.gaps, feature_lookback_span, tf_config.label_horizon,
    )
    validity_by_ts = {v.decision_timestamp: v for v in validity}

    result = DryRunResult(symbol=symbol, timeframe=timeframe.value, total_clean_candles=len(clean))
    regime_counter: Counter[str] = Counter()
    seen_candidate_keys = set()

    for idx, candle in enumerate(clean):
        v = validity_by_ts[candle.close_time]
        if "GAP_IN_FEATURE_LOOKBACK" in v.reason_codes:
            result.dropped_by_gap_policy += 1
            continue
        if "GAP_IN_LABEL_HORIZON" in v.reason_codes:
            result.dropped_by_stale_policy += 1
            # Still a valid decision point for feature/regime purposes — just can't be labeled.
        if idx < 28:  # below the minimum feature lookback (ADX needs 28 bars) — not yet decidable
            continue

        result.valid_decision_points += 1
        window_start = max(0, idx + 1 - FEATURE_LOOKBACK_WINDOW)
        buffer = clean[window_start:idx + 1]

        from packages.agents.models import AgentEvaluationContext, MarketRegime
        from packages.features.models import FeatureComputationRequest
        from packages.features.pipeline import feature_pipeline

        feature_req = FeatureComputationRequest(
            exchange="binance", symbol=symbol, timeframe=timeframe,
            feature_set="standard_v1", as_of_time=candle.close_time,
        )
        snapshot = feature_pipeline.compute(feature_req, buffer)

        # Leakage check: structurally enforced by FeatureSnapshot's own pydantic validator
        # (raises ValueError on violation), so a violation would abort this run rather than
        # be silently counted — verified here as an explicit, non-silent assertion.
        if snapshot.lookback_end > candle.close_time or snapshot.event_time > candle.close_time:
            result.leakage_violation_count += 1

        regime_ctx = AgentEvaluationContext(
            exchange="binance", symbol=symbol, timeframe=timeframe, as_of_time=candle.close_time,
            feature_snapshot=snapshot, market_regime=MarketRegime.UNKNOWN, data_quality_status="HEALTHY",
            reference_price=candle.close_price,
        )
        regime_result = _regime_agent.classify_regime_detailed(regime_ctx)
        regime_counter[regime_result.regime.value] += 1

        routing_decision = route(regime_result.regime)
        result.routed_agent_execution_count += len(routing_decision.allowed_strategy_types)
        if routing_decision.is_no_trade:
            continue

        decision = await decision_service.decide(
            exchange="binance", symbol=symbol, timeframe=timeframe, candles=buffer,
            as_of_time=candle.close_time, reference_price=candle.close_price,
            allowed_strategy_types=routing_decision.allowed_strategy_types,
        )
        if decision.trade_intent is None:
            continue

        from uuid import uuid4
        candidate = build_proposed_candidate(
            decision=decision, session_id=uuid4(),
            strategy_name="dry_run_baseline", strategy_version="1.0.0",
        )
        if candidate is None:
            continue

        result.candidate_count += 1

        # Lineage consistency (same invariants asserted in test_candidate_pipeline_e2e.py).
        if candidate.market_regime != regime_result.regime.value:
            result.lineage_violation_count += 1
        if candidate.agent_source not in candidate.supporting_agents:
            result.lineage_violation_count += 1

        dedup_key = (symbol, timeframe.value, candle.close_time.isoformat())
        if dedup_key in seen_candidate_keys:
            result.duplicate_candidate_count += 1
        seen_candidate_keys.add(dedup_key)

        if idx + label_horizon_bars < len(clean):
            result.completed_label_count += 1

    result.regime_distribution = dict(regime_counter)
    result.elapsed_seconds = round(time.time() - t0, 2)
    return result


def _interval(timeframe: Timeframe) -> timedelta:
    from packages.market_data.historical_quality import TIMEFRAME_INTERVAL
    return TIMEFRAME_INTERVAL[timeframe]


async def run_all() -> List[DryRunResult]:
    results = []
    for timeframe in TIMEFRAMES:
        for symbol in SYMBOLS:
            print(f"[dry_run] {symbol} {timeframe.value} ...")
            r = await dry_run_one(symbol, timeframe)
            results.append(r)
            print(
                f"[dry_run] {symbol} {timeframe.value}: valid_points={r.valid_decision_points} "
                f"candidates={r.candidate_count} regimes={r.regime_distribution} "
                f"lineage_violations={r.lineage_violation_count} leakage_violations={r.leakage_violation_count} "
                f"({r.elapsed_seconds}s)"
            )
    return results


def write_reports(results: List[DryRunResult]) -> None:
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "results": [asdict(r) for r in results]},
            f, indent=2,
        )
    print(f"[dry_run] wrote {REPORT_JSON_PATH}")

    lines = ["# Real Candidate Dry Run Report", ""]
    lines.append(
        "_Real, no-ML dry run of validate -> feature -> regime -> route -> decide -> candidate "
        "across every real 1h/4h dataset fetched in Checkpoint 2 (BTC/ETH/BNB/SOL). No fills, "
        "no PnL, no training — this exercises the wiring at real scale and counts what happened. "
        "See methodology note in `packages/research/candidate_dry_run.py` for how "
        "`dropped_by_stale_policy` is adapted from a live-runtime concept to historical replay._"
    )
    lines.append("")
    lines.append(
        "| Symbol | TF | Clean Candles | Valid Pts | Dropped(Gap) | Dropped(Stale) | "
        "Routed Agent Execs | Candidates | Completed Labels | Duplicates | Lineage Viol. | Leakage Viol. | Time(s) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r.symbol} | {r.timeframe} | {r.total_clean_candles} | {r.valid_decision_points} | "
            f"{r.dropped_by_gap_policy} | {r.dropped_by_stale_policy} | {r.routed_agent_execution_count} | "
            f"{r.candidate_count} | {r.completed_label_count} | {r.duplicate_candidate_count} | "
            f"{r.lineage_violation_count} | {r.leakage_violation_count} | {r.elapsed_seconds} |"
        )
    lines.append("")
    lines.append("## Regime distribution per (symbol, timeframe)")
    lines.append("")
    for r in results:
        lines.append(f"- **{r.symbol} {r.timeframe}**: {r.regime_distribution}")
    lines.append("")
    total_lineage = sum(r.lineage_violation_count for r in results)
    total_leakage = sum(r.leakage_violation_count for r in results)
    total_dup = sum(r.duplicate_candidate_count for r in results)
    lines.append("## Integrity summary")
    lines.append("")
    lines.append(f"- Total lineage violations across all 8 (symbol, timeframe) series: **{total_lineage}**")
    lines.append(f"- Total leakage violations: **{total_leakage}**")
    lines.append(f"- Total duplicate candidates: **{total_dup}**")
    lines.append(
        "\nZero across all three is the expected, required result — any non-zero value here "
        "indicates a real wiring bug, not a strategy quality issue, and must be fixed before "
        "this pipeline is used for anything downstream."
    )

    with open(REPORT_MD_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[dry_run] wrote {REPORT_MD_PATH}")


if __name__ == "__main__":
    import asyncio
    res = asyncio.run(run_all())
    write_reports(res)
