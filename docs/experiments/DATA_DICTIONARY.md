# Experimental Data Dictionary

Schema: `experiment_record_v1`

## Identity and time

| Field | Meaning |
|---|---|
| `experiment_id` | SHA-256 ID derived from analysis identity, market scope, as-of time, input/evidence checksums, model versions and prompt versions. |
| `analysis_id` | Upstream analysis request identity. |
| `sequence_number` | Unique append order within one store/export. |
| `symbol`, `timeframe` | Exact market scope. |
| `as_of_time` | Latest time information may influence the analysis. |
| `recorded_at` | Time the complete experimental envelope was recorded; must not precede `as_of_time`. |

## Captured lineage

`raw_inputs`, `normalized_inputs`, `feature_snapshot`, `evidence_snapshot`,
`agent_outputs`, `debate_transcript`, `verification_result`, `risk_result`,
`manager_result`, `actual_market_outcome` and `data_quality` are canonical JSON payloads.
Each carries its own SHA-256 checksum. Secret-like keys and credential-bearing DSNs are rejected
before capture rather than redacted into the experimental store.

Actual outcomes are separate immutable `experiment_outcome_v1` events linked by
`experiment_id` and a unique horizon. Each event records `outcome_available_at`,
`observed_at`, actual market payload/checksum, optional correctness, paper PnL/currency,
simulated return and drawdown. Availability must be no earlier than the parsed `m`/`h`/`d`
horizon target after analysis time; an outcome can mature later without rewriting the original
experiment.

Nullable outcome fields mean not observed/evaluated; null is never converted to zero or
counted as an incorrect prediction. Paper PnL is explicitly simulated and must not be
described as live performance.

## Version and telemetry fields

| Field | Meaning |
|---|---|
| `model_versions` | Exact role-to-model version mapping used by the analysis. |
| `prompt_versions` | Exact role-to-prompt version mapping. |
| `input_tokens`, `output_tokens` | Observed provider token counts; null when unavailable. |
| `cost_amount`, `cost_currency` | Observed comparable provider cost; both present or both null. |
| `latency_ms` | Observed end-to-end latency. |
| `retry_count`, `error_codes` | Actual retry/error observations. |
| `expected_field_count`, `missing_field_count` | Explicit denominator/numerator for missing-data reporting. |
| `agent_disagreement` | Observed disagreement flag; null when not evaluated. |
| `verification_rejected` | Whether Verification rejected the analysis. |

## Export and retention

- Export format is UTF-8 canonical JSON Lines with explicit `EXPERIMENT`/`OUTCOME` record type.
- The first line is a `MANIFEST` with schema versions, counts and the exact retention policy.
- Export refuses to overwrite an existing path using atomic no-clobber publication and fsyncs
  both the file and containing directory.
- Default retention is 365 days with `MANUAL_AUDITED` deletion and archive-before-delete.
- The in-process store never deletes or overwrites a record automatically.
- The store exposes deterministic expired-record candidates from policy and record time.
  Its retention bundle includes dependent outcome IDs, policy version and archive requirement.
  Archive/delete execution still requires a separate audited operator workflow.

Reports require an explicit horizon cohort. Accuracy, PnL, win rate and drawdown never pool
overlapping horizons; observation counts expose every metric denominator.
