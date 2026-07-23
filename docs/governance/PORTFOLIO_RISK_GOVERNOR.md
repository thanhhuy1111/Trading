# Portfolio Risk Governor (Phase 6)

`packages/risk/portfolio_governor.py: BaselinePortfolioRiskGovernor`. Distinct from
`packages/risk/governor.py: DeterministicRiskGovernor` (the pre-existing per-trade governor
used by paper trading/backtesting) - this operates one level up: given a candidate that has
already cleared per-trade sizing, decide whether the PORTFOLIO as a whole can additionally take
it on. A candidate must clear both governors; neither replaces the other.

## Decision type - always exactly one of four

`APPROVE`, `REDUCE`, `REJECT`, `HALT` (`PortfolioRiskDecisionType`). Every `PortfolioRiskDecision`
carries `policy_version`, `candidate_id`, `requested_risk_pct`, `approved_risk_pct`, and
`reason_codes` - a HALT/REJECT/REDUCE is always reproducible from its recorded inputs.

## `PortfolioRiskPolicy` (11 named limits)

`max_risk_per_candidate_pct` (0.25%), `max_total_open_risk_pct` (2.0%),
`max_simultaneous_positions` (5), `max_single_asset_exposure_pct` (20%),
`max_same_direction_exposure_pct` (50%, declared, not yet enforced by `evaluate()`),
`max_correlated_exposure_pct` (30%), `correlated_threshold` (|correlation| >= 0.7 counts as
correlated), `daily_loss_limit_pct` (1.5%), `weekly_loss_limit_pct` (4.0%),
`portfolio_drawdown_limit_pct` (8.0%), plus `version` (`policy_version="portfolio_risk_v1"`).
Every threshold is declared up front, not tuned to any backtest result.

## Evaluation order (`evaluate()`)

1. Missing portfolio state (`PortfolioSnapshot.available=False`) -> `HALT` (never an implicit
   `APPROVE`).
2. Kill switch active -> `HALT`.
3. Portfolio drawdown breaker -> `HALT`.
4. Daily / weekly loss limits -> `HALT`.
5. Stale data / low liquidity / non-actionable evidence -> `REJECT` (candidate-specific, so
   `REJECT` not `HALT`).
6. Max simultaneous positions -> `REJECT`.
7. Per-candidate cap -> `REDUCE` if exceeded.
8. Total open risk cap -> `REJECT` if already full, else `REDUCE` if exceeded.
9. Single-asset exposure cap -> `REJECT` if already full, else `REDUCE` if exceeded.
10. Correlated-exposure cap -> `REJECT` if already full, else `REDUCE` if exceeded. A missing
    correlation snapshot for a held symbol is treated as "assume correlated" - conservative,
    never treated as zero/uncorrelated (`_correlated_exposure`).
11. Otherwise -> `APPROVE`.

## Structural isolation from the LLM layer

`packages/risk/portfolio_governor.py` has no import path to `packages.intelligence` or
`packages.llm` - the LLM/market-context layer cannot override a risk decision, not just by
convention. `MarketContextAssessment.risk_adjustment` is read elsewhere (the ranking service,
informationally) but is never wired into `PortfolioRiskPolicy` or `evaluate()`.

## Where it's consulted

`packages.runtime.recommendation_service` calls `evaluate()` for every proposal, binding once
evidence is actionable, advisory (prefixed `ADVISORY_RISK:` in `reason_codes`) otherwise - see
`docs/runtime/RECOMMENDATION_RUNTIME.md`.
