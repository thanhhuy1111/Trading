# Recommendation Runtime (Phase 7)

`packages/runtime/recommendation_service.py: BaselineRecommendationService` is the single
end-to-end orchestrator. Every dependency (candles, portfolio snapshot, every intelligence
service) is constructor-injected, so the whole flow is testable offline with fixture candles
and fake services - it never reaches for a live network client itself.

## Flow

```
candles -> packages.governance.candidate_pipeline.run_candidate_pipeline
             (data quality -> features -> regime -> strategy routing -> agents -> candidate)
         -> meta-label predict()
         -> market context assess() (advisory only)
         -> exact-match evidence lookup
         -> ranking
         -> correlation + strategy portfolio (informational for research, binding for approved)
         -> portfolio risk governor evaluate()
         -> TradeProposal, or an explicit non-trade ApplicationResultState
```

## The 11 `ApplicationResultState` values

Each is reachable and mutually exclusive by construction:

| State | Trigger |
|---|---|
| `NO_CANDIDATE` | No candles at all, or the pipeline found no tradeable signal. |
| `DATA_QUALITY_FAILED` | Dataset rejected for severe gaps, or no candle at the decision time. |
| `STALE_DATA` | Freshest candle older than `config.staleness_threshold`. |
| `NO_TRADE` | A candidate was built but the meta-label service rejected it. |
| `MODEL_NOT_AVAILABLE` | `config.require_trained_model=True` and no trained model is usable. |
| `STRATEGY_NOT_APPROVED` | The exact-match evidence record is explicitly `REJECTED`/`DISABLED`. |
| `INSUFFICIENT_EVIDENCE` | `config.require_actionable_evidence=True` and no `APPROVED` record exists. |
| `RESEARCH_PROPOSAL` | Default, permissive path: a proposal is produced without approved evidence. |
| `RISK_LIMIT_EXCEEDED` | Evidence actionable, portfolio risk governor rejected/halted (not missing state). |
| `SYSTEM_DEGRADED` | Portfolio state unavailable, or any unexpected exception (caught once, surfaced). |
| `APPROVED_PROPOSAL` | Evidence actionable and the risk governor approved/reduced the request. |

`RESEARCH_PROPOSAL` is the deliberately permissive default so Phase 10 shadow mode always has
something to evaluate, even with an empty evidence registry. `INSUFFICIENT_EVIDENCE` is the
strict alternative, opted into via `RecommendationServiceConfig.require_actionable_evidence`.

## `RecommendationServiceConfig`

`strategy_config`, `strategy_name`/`strategy_version`, `feature_lookback_bars`,
`staleness_threshold`, `requested_risk_pct`, `require_trained_model`,
`require_actionable_evidence`.

## `scan()` vs `analyze()`

`analyze()` runs one symbol. `scan()` runs every symbol in the request independently - one
symbol's failure or non-trade result never blocks another - and reports a coarse aggregate
`application_result_state` (the "best" state seen, per `_STATE_RANK`), while every symbol's
own reason codes are folded into the result prefixed with the symbol name and each
`TradeProposal` still carries its own authoritative state.

## Error handling

`_analyze_one` wraps `_analyze_one_unsafe` in exactly one `try/except Exception`, at the
per-symbol boundary. An unexpected exception becomes `SYSTEM_DEGRADED` with
`UNEXPECTED_ERROR:<type>:<message>` in `reason_codes` - never silently swallowed, never raised
past this boundary to crash a `scan()` over other symbols.
