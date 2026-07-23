# Service Interfaces (Ports)

`packages/ports/interfaces.py` declares 20 `typing.Protocol` classes - structural typing, so a
concrete adapter (baseline, LLM-backed, DB-backed) never needs to inherit from anything here,
it just needs to match the method signatures. This keeps domain/application code free of
concrete infrastructure imports.

Each Protocol documents its typed I/O, timeout policy (where it has an external dependency),
and whether it's expected to be deterministic. Errors are typed (`packages/ports/errors.py`:
`PortError` and 8 subclasses), never a bare `Exception`.

## Universe & market data
- `UniverseService` - `current_snapshot()` (instant, pure) / `refresh()` (network, 20s timeout).
- `MarketDataService` - `load_closed_candles()` (network, 20s timeout) / `dataset_metadata()`.
- `DataQualityService` - `validate()`, pure/deterministic.
- `FeatureService` - `compute()`, pure/deterministic.
- `RegimeService` - `classify()`, pure/deterministic.
- `StrategyRouterPort` - `route()`, pure/deterministic.
- `AgentService` - `evaluate()`, deterministic given identical inputs (no LLM, no randomness).
- `CandidateService` - `build()`, pure.

## Intelligence layer
- `MetaLabelService` - `predict()`. The honest baseline (`probability=None`,
  `decision=DEFER_TO_EXISTING_RULES`) is required whenever no trained model is available.
- `MarketContextService` - `assess()`, aggregates 4 LLM agents; must work with all disabled.
- `RankingService` - `rank()`, deterministic; `RESEARCH_ONLY` status required whenever expected
  edge or calibrated probability is unavailable.
- `CorrelationService` - `snapshot()`; never 0.0 for missing/insufficient sample.
- `StrategyPortfolioService` - `eligible_sleeves()`.

## Governance
- `EvidenceService` - `lookup()`, exact-match only, deterministic.
- `PortfolioRiskService` - `evaluate()`, always one of APPROVE/REDUCE/REJECT/HALT; missing
  state -> conservative, never implicit APPROVE.

## Runtime
- `RecommendationService` - `scan()` / `analyze()`, 30s timeout; must return a typed
  `RecommendationResult` even when every intelligence layer is degraded/disabled/empty.

## Shadow / Monitoring / Drift / Retraining
- `ShadowService` - `record_proposal()` / `schedule_evaluation()` / `evaluate_due()`.
- `MonitoringService` - `record_metric()` / `current_readiness()`.
- `DriftService` - `assess()`.
- `RetrainingService` - `run_training_job()`; no method on this Protocol can promote a model -
  promotion is a separate, human-gated registry operation.

## Lightweight request/response shapes

Not covered by a domain entity: `RecommendationRequest`/`RecommendationResult`,
`EvidenceLookupOutcome`, `PortfolioSnapshot` (its `available: bool` field represents missing
state explicitly, rather than every field being `None`).

## Concrete implementations

Live under `packages/intelligence/`, `packages/risk/`, `packages/llm/`, `packages/shadow/`,
`packages/monitoring/`, `packages/retraining/` - `packages/ports/interfaces.py` only declares
the contracts, never a concrete adapter.
