# Monitoring and Metrics (Phase 11)

`packages/monitoring/{metrics,service}.py`.

## The 20 named metrics

`packages/monitoring/metrics.py: ALL_METRIC_NAMES` (asserted to be exactly 20 by
`tests/unit/test_monitoring.py::test_exactly_twenty_named_metrics`):

| Category | Metrics |
|---|---|
| Data / pipeline health | `candles_ingested_total`, `data_quality_rejected_total`, `stale_data_events_total` |
| Candidate generation | `candidates_generated_total`, `router_no_trade_total`, `no_trade_events_total` |
| Meta-label / model | `model_not_available_total`, `meta_label_rejected_total` |
| Evidence | `evidence_lookups_total`, `evidence_mismatch_total`, `evidence_missing_total`, `evidence_stale_total` |
| Ranking / proposals | `proposals_research_total`, `proposals_approved_total` |
| Portfolio risk | `risk_rejected_total`, `risk_halted_total`, `risk_reduced_total` |
| Shadow mode | `shadow_proposals_recorded_total`, `shadow_outcomes_evaluated_total` |
| System | `system_degraded_events_total` |

No metric name implies a target or claims profitability - they are counters an operator reads,
not a scorecard this campaign optimized against.

## Recording and readiness

`BaselineMonitoringService.record_metric(name, value, tags)` records to an
`InMemoryMetricsStore`; a name outside `ALL_METRIC_NAMES` is still recorded (an operator adding
a new metric isn't blocked) but tagged `unregistered_metric_name=true` so drift in the named
set stays visible.

`current_readiness()` reads live from the injected `EvidenceStore` - the exact same
conservative logic `apps/api/routers/recommendations.py: GET /readiness` uses - so neither can
drift from the other or from reality. See `docs/architecture/READINESS_AXES.md`.

## Where metrics get recorded from

This campaign wires the metric *names* and the recording/storage machinery; it does not
retrofit every existing pipeline stage to call `record_metric()` on every event (that would be
scope creep well beyond "complete the architecture"). `tests/acceptance/test_final_acceptance.py`
demonstrates one call (`PROPOSALS_RESEARCH_TOTAL`) as part of the full end-to-end scenario. A
future campaign wiring metrics calls throughout `packages.runtime.recommendation_service` and
`packages.shadow.service` is a natural, additive next step that does not require touching this
module's public API.
