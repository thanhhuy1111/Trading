# Architecture Overview

This document describes the 20-stage architecture built across Checkpoints 1-2 (Phases 0-6:
data/domain/registries/intelligence/evidence/risk foundations) and this campaign (Phases 7-12:
runtime, API, LLM framework, shadow mode, monitoring, retraining). It is an architecture
description, not a profitability claim - see `docs/ARCHITECTURE_COMPLETION_REPORT.md` for the
scope and explicit non-claims.

## The 20 stages

1. **Dynamic Universe** - `packages/universe/` (selector.py pure/offline, live_source.py the
   only network-touching piece).
2. **Market Data** - `packages/market_data/` (Candle model with construction-time OHLC
   integrity validation, Binance public adapter).
3. **Data Quality** - `packages/market_data/historical_quality.py`
   (`validate_historical_series`: VALIDATED/DEGRADED/REJECTED, raw vs. clean status split).
4. **Feature Engine** - `packages/features/` (calculator registry + `FeaturePipeline`, strict
   point-in-time computation).
5. **Regime Detection** - `packages/agents/regime.py` (`MarketRegimeAgent`).
6. **Strategy Router** - `packages/governance/strategy_router.py` (deterministic regime ->
   allowed strategy types table).
7. **Trading Agents** - `packages/agents/{trend,reversion,breakout}.py` (rule-based, no LLM).
8. **Candidate Aggregation** - `packages/governance/{consensus,critic,allocator}.py` +
   `packages/candidates/builder.py`.
9. **Meta-label Service** - `packages/intelligence/meta_label.py`
   (`PassThroughMetaLabelService` is the only one actually active; LR/Tree services define the
   real interface for Checkpoint 3's trained models).
10. **LLM Market Context** - `packages/intelligence/market_context.py` (Phase 4 no-op agents)
    + `packages/llm/` (Phase 9's fuller framework: timeout/retry/circuit-breaker, defensive
    input/output handling, 5 named interfaces).
11. **Evidence Gate** - `packages/evidence/` (exact-match-only `EvidenceStore`, 8-value
    `EvidenceStatus`, typed lookup results, audit log).
12. **Opportunity Ranking** - `packages/intelligence/ranking.py`
    (`BaselineRankingService`, a documented linear scoring formula).
13. **Correlation Service** - `packages/intelligence/correlation.py`
    (`BaselineCorrelationService`, real Pearson correlation, never 0.0 for missing data).
14. **Strategy Portfolio** - `packages/intelligence/strategy_portfolio.py` (`StrategySleeve`,
    `StrategyPortfolio`).
15. **Portfolio Risk Governor** - `packages/risk/portfolio_governor.py`
    (`BaselinePortfolioRiskGovernor`, APPROVE/REDUCE/REJECT/HALT).
16. **Recommendation Service** - `packages/runtime/recommendation_service.py`
    (`BaselineRecommendationService`, the Phase 7 end-to-end orchestrator).
17. **API / Chat Runtime** - `apps/api/routers/recommendations.py` (11 endpoints, Phase 8).
18. **Shadow Mode** - `packages/shadow/` (Phase 10: immutable snapshots, outcome evaluation,
    calibration aggregation).
19. **Monitoring** - `packages/monitoring/{metrics,service}.py` (Phase 11: 20 named metrics,
    six-axis readiness).
20. **Drift Detection / Retraining Workflow** - `packages/monitoring/{drift,evidence_lifecycle}.py`
    + `packages/retraining/workflow.py` (Phase 11-12).

## Design principles carried through every stage

- **Exact-match, no fallback.** Evidence, registries, and feature/model versions never
  substitute a "close enough" match - see `docs/governance/EVIDENCE_LIFECYCLE.md` and
  `docs/architecture/REGISTRY_DESIGN.md`.
- **Honest baselines.** Every intelligence layer (meta-label, market context/LLM) has a
  working, tested "not available" response instead of a fabricated one. The system is designed
  to run correctly with every one of these disabled.
- **Conservative missing-state handling.** Missing portfolio state -> HALT. Missing
  correlation -> assume correlated. Missing drift baseline -> flagged, not silently "no drift."
- **No silent exception swallowing.** `packages/runtime/recommendation_service.py`'s
  `_analyze_one` catches exactly once, at the per-symbol boundary, and always surfaces the
  exception type/message in `reason_codes` as `SYSTEM_DEGRADED` - it never disappears.
- **Six independent readiness axes, never conflated** - see `docs/architecture/READINESS_AXES.md`.

## Where each Master Plan phase landed

| Phase | Subject | Primary module(s) |
|---|---|---|
| 0 | Data/quality diagnostics, mypy fixes, real dry run | `packages/research/`, `packages/market_data/historical_quality.py` |
| 1 | Domain entities, six readiness axes | `packages/domain/{enums,entities}.py` |
| 2 | Service interfaces (20 Protocols) | `packages/ports/{interfaces,errors}.py` |
| 3 | 7 artifact registries | `packages/registries/` |
| 4 | Baseline intelligence (meta-label, context, ranking, correlation, sleeves) | `packages/intelligence/` |
| 5 | Evidence lifecycle + audit | `packages/evidence/{models,store,audit}.py` |
| 6 | Portfolio risk governor | `packages/risk/portfolio_governor.py` |
| 7 | Recommendation runtime | `packages/runtime/recommendation_service.py` |
| 8 | API layer | `apps/api/routers/recommendations.py`, `apps/api/deps.py`, `apps/api/error_schema.py` |
| 9 | LLM agent framework | `packages/llm/` |
| 10 | Shadow mode | `packages/shadow/` |
| 11 | Monitoring / drift | `packages/monitoring/` |
| 12 | Retraining workflow | `packages/retraining/workflow.py` |
