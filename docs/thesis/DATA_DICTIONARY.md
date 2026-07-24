# Thesis Cohort Data Dictionary

The canonical experiment and outcome fields are defined in
`docs/experiments/DATA_DICTIONARY.md`. This document adds only thesis-analysis fields; it does
not replace or weaken that schema.

| Field | Meaning |
|---|---|
| `schema_version` | Exact `thesis_experiment_identity_v1` identity schema. |
| `thesis_experiment_id` | SHA-256 over base experiment, protocol, variant/config, cohort, pair, as-of time and market scope. |
| `base_experiment_id` | Canonical Phase 13 experiment envelope identity; never used alone for an ablation row. |
| `base_record_checksum` | Canonical SHA-256 of the complete validated Phase 13 `ExperimentRecord`. |
| `protocol_sha256` | Pinned SHA-256 of the pre-outcome protocol-v1 record. |
| `variant_id` | One exact variant from the required ablation matrix. |
| `cohort_id` | Deterministic identity for symbol, timeframe, horizon, fold, and protocol. |
| `fold_id` | Predeclared temporal fold; never a random row split. |
| `horizon` | Canonical outcome horizon; evaluated separately from other horizons. |
| `eligibility_status` | `ELIGIBLE`, `UNAVAILABLE`, `REJECTED`, or `EXCLUDED`. |
| `eligibility_reason_codes` | Ordered protocol-defined reasons; empty only when eligible. |
| `paired_analysis_id` | Shared analysis identity used to enforce variant input parity. |
| `variant_config_sha256` | SHA-256 of the immutable variant configuration. |
| `simulated_execution` | Must be `true` for paper portfolio outcomes. |
| `result_status` | `PENDING_EVIDENCE` until the full cohort acceptance gate passes. |

`packages.experiments.thesis_protocol.ThesisExperimentIdentity` is the executable identity
model. The builder creates ten unique IDs for one paired clock even when variants share most
components. The future collection adapter must persist this identity beside the canonical
Phase 13 envelope; a base `experiment_id` alone is insufficient. The builder revalidates the
full `ExperimentRecord`, cross-checks symbol/timeframe/as-of/cadence, requires capture before
the 4h outcome matures, and binds its canonical checksum.

## Null and status semantics

- Null means not observed or not applicable; it is never converted to zero.
- `UNAVAILABLE` is an operational outcome, not a negative market label.
- `REJECTED` preserves the safety-gate reason.
- `EXCLUDED` is allowed only with a predeclared reason code.
- Paper PnL and return are simulated and never named live performance.
- Variant and cohort records are append-only and checksum-addressed.

## Join rules

Join thesis identities to experiment envelopes by `base_experiment_id`, then verify the full
envelope against the pinned protocol and `base_record_checksum` using `validate_binding()`.
Join matured outcomes by
`(base_experiment_id, horizon)`, and join paired thesis variants by
`(paired_analysis_id, symbol, timeframe, as_of_time, horizon)`. A join that changes row
cardinality, duplicates `thesis_experiment_id`, or mixes horizons fails validation.
