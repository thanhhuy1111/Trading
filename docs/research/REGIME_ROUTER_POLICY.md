# Point-in-Time Regime Detection & Strategy Router Policy

## Regime detection

`packages/agents/regime.py: MarketRegimeAgent.classify_regime_detailed` wraps the existing
`classify_regime` (same ADX/EMA-slope/volatility thresholds — single source of truth, no
duplicated logic that could drift) and adds the audit fields the Master Plan requires:

```
regime            — MarketRegime (TREND_UP, TREND_DOWN, SIDEWAYS, HIGH_VOLATILITY,
                     LOW_VOLATILITY, TRANSITION, LIQUIDITY_RISK, UNKNOWN)
confidence        — heuristic score in [0,1], NOT a calibrated statistical probability
                     (Master Plan principle 7 — never treat this as a real probability
                     downstream); derived from how far the deciding feature is past its
                     threshold
regime_version    — the agent's version string
calculated_at     — wall-clock time this classification actually ran
feature_timestamp — the as_of_time the underlying features were computed from (the point in
                     time this classification is FOR, distinct from calculated_at, the point
                     in time it was computed AT — these differ in backtests by design)
reason_codes      — why this regime fired (e.g. ADX_ABOVE_TREND_THRESHOLD, EMA_SLOPE_UP)
```

**Point-in-time guarantee**: classifying at time T gives an identical result whether or not
candles after T exist in the input series — proven by
`tests/unit/test_regime_detail.py::test_point_in_time_regime_is_invariant_to_future_candles`.
This follows from `FeaturePipeline.compute`'s own `close_time <= as_of_time` filter; the
regime classifier only ever sees what that filter already restricted it to.

## Strategy Router

`packages/governance/strategy_router.py: route(regime) -> RoutingDecision` — deterministic,
versioned (`ROUTER_VERSION = "router_v1"`), one explicit table entry per `MarketRegime` (no
default fallthrough):

| Regime | Routed strategy types | Rationale |
|---|---|---|
| `TREND_UP` | `{TREND_FOLLOWING}` | See "known gap" below re: Pullback |
| `TREND_DOWN` | `{TREND_FOLLOWING}` | Routed for honesty about what regime was seen; has no executable effect today since the allocator is spot-long-only (see below) |
| `SIDEWAYS` | `{MEAN_REVERSION}` | |
| `HIGH_VOLATILITY` | `{BREAKOUT}` | |
| `LOW_VOLATILITY` | `{MEAN_REVERSION}` | Tight ranges favor reversion over trend/breakout continuation |
| `LIQUIDITY_RISK` (maps to the Master Plan's "LOW_LIQUIDITY") | `{}` (NO_TRADE) | |
| `TRANSITION` (maps to "UNCERTAIN") | `{}` (NO_TRADE) | |
| `UNKNOWN` | `{}` (NO_TRADE) | Insufficient feature data to classify at all |

**Known, stated gap**: the platform has no Pullback agent implemented (only Trend, Mean
Reversion, Breakout exist — `packages/agents/{trend,reversion,breakout}.py`). The Master
Plan's example table routes `TREND_UP` to "Trend Long + Pullback Long"; this router routes to
`{TREND_FOLLOWING}` only. Routing to a `StrategyType` with no agent behind it would silently
no-op while looking like a real routing decision — that would be worse than stating the gap.

**Spot long-only limitation**: `TREND_DOWN` is still routed to `TREND_FOLLOWING` (the agent
runs and can produce a signal), but `packages/governance/allocator.py`'s Gate 2 already
rejects any `SHORT` consensus direction (`SPOT_SHORT_NOT_EXECUTABLE`) regardless of routing.
The router's decision and the allocator's execution policy are deliberately kept as two
separate, independently-inspectable layers.

## Wiring into DecisionService

`packages/governance/decision_service.py: DecisionService.decide` gained an optional
`allowed_strategy_types` parameter. When given (by the router), only agents whose
`StrategyType` is in the set actually run — `evaluate()` is never called for a filtered-out
agent, not run-then-discarded. `None` (the default, used by every existing caller — paper
trading, the Checkpoint 1 backtest campaign) preserves the exact original always-run-all-three
behavior; confirmed by the full test suite passing unchanged.

An empty allowed set (what `LIQUIDITY_RISK`/`TRANSITION`/`UNKNOWN` route to) runs zero agents.
This flows through the *existing* consensus (`INSUFFICIENT_EVIDENCE`) and allocator
(`NO_TRADE`) logic with no special-casing required — proven by
`tests/unit/test_decision_service_routing.py::test_empty_allowed_set_runs_zero_agents_and_forces_no_trade`.

## End-to-end proof

`packages/governance/candidate_pipeline.py: run_candidate_pipeline` chains everything built
this checkpoint:

```
raw candles -> validate_historical_series -> feature_pipeline -> classify_regime_detailed
-> strategy_router.route -> DecisionService.decide(allowed_strategy_types=...) -> TradeCandidate
```

with an explicit staleness guard (rejects generating a candidate if the latest candle is older
than a caller-supplied threshold relative to "now" — `STALE_DATA`) and full lineage
consistency checks: `tests/unit/test_candidate_pipeline_e2e.py` (6 tests, including the
no-leakage invariance test: candles beyond `as_of_time` never change the output).
