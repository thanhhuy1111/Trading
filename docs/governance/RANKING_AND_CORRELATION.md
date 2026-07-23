# Ranking, Correlation, and Strategy Portfolio (Phase 4)

## Ranking - `packages/intelligence/ranking.py`

`BaselineRankingService.rank()` is a documented, versioned (`RANKING_VERSION = "ranking_v1"`)
linear scoring formula, not a machine-learned ranker - given the same inputs it always returns
the same order (`tests/unit/test_intelligence_baseline.py::test_ranking_is_deterministic_given_identical_inputs`).

```
score = WEIGHT_EXPECTED_EDGE * edge_term
      + WEIGHT_EVIDENCE * evidence_weight
      + WEIGHT_LIQUIDITY * liquidity_score
      + WEIGHT_FRESHNESS * data_freshness_score
      - WEIGHT_COST_PENALTY * cost_penalty
      - WEIGHT_CORRELATION_PENALTY * correlated_exposure_score
      - WEIGHT_RISK_PENALTY * risk_score
```

Weights (`1.0`/`0.5`/`0.2`/`0.2`/`1.0`/`0.5`/`0.5`) are declared up front, not tuned to any
backtest result. Missing `expected_net_edge_bps` or `calibrated_probability` -> `edge_term=0`
and `ranking_status=RESEARCH_ONLY` (never a fabricated edge). `evidence_weight` comes from a
fixed table keyed by `EvidenceStatus` (`UNIVERSAL_APPROVED`=1.0 down to `DEGRADED`=0.1; no
entry for `RESEARCH_ONLY`/`INSUFFICIENT`/`REJECTED`/`STALE`/`DISABLED` -> weight 0).

## Correlation - `packages/intelligence/correlation.py`

`BaselineCorrelationService.snapshot()` computes real point-in-time Pearson correlation
(`statistics.correlation`, stdlib only) over aligned close-to-close returns.
`correlation=None` (never `0.0`) whenever the sample is too small
(`MINIMUM_SAMPLE_COUNT=30`) or no candles are available - a caller that treats `None` as
"uncorrelated" is making its own choice; this service never makes that choice for it. Status
values: `OK`, `INSUFFICIENT_SAMPLE`, `STALE`, `UNAVAILABLE`.

## Strategy Portfolio - `packages/intelligence/strategy_portfolio.py`

`StrategySleeve` - a curated allocation unit: `strategy_id`, `symbol`, `timeframe`,
`regime_scope`, `risk_budget_pct`, `allocation_weight`, `evidence_status`, `model_version`,
`drawdown_limit_pct`, `enabled`. `is_approved_eligible` is true only for
`UNIVERSAL_APPROVED`/`ASSET_SPECIFIC_APPROVED` evidence status.

`StrategyPortfolio.eligible_sleeves(symbol, timeframe, regime)` - every enabled sleeve matching
exactly, regardless of evidence status (so shadow mode can still see research-only sleeves).
`approved_sleeves(...)` filters that down to `is_approved_eligible` ones.

An empty, uncurated `StrategyPortfolio()` is this baseline's expected default state, not an
error - `packages.runtime.recommendation_service` consults it informationally
(`NO_STRATEGY_SLEEVE_REGISTERED` / `STRATEGY_SLEEVE_RESEARCH_ONLY` /
`STRATEGY_SLEEVE_APPROVED_ELIGIBLE` in `reason_codes`), never as a hard block.
