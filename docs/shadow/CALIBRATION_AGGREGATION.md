# Calibration Aggregation

`packages.shadow.service.aggregate_calibration()` is the bridge between shadow-mode outcomes
and "is this model's `calibrated_probability` actually meaningful" - a question this campaign
does not answer (no accuracy optimization was performed), but the plumbing to answer it later
is built and tested now.

## Method

1. For each `ShadowProposal`, look up its resolved `ShadowOutcome` (skip if `PENDING` or
   `DATA_UNAVAILABLE`).
2. Read `calibrated_probability` from the proposal's frozen `candidate_snapshot` (skip if
   absent - `PassThroughMetaLabelService`, the only meta-label service actually active in this
   task, always returns `probability=None`, so this campaign's own shadow records will not
   populate any bucket; a future campaign with a real trained model will).
3. Bucket by `floor(probability / bucket_width) * bucket_width` (default decile buckets:
   `[0.0-0.1)`, `[0.1-0.2)`, ...).
4. Within each bucket, `realized_win_rate = count(net_return_bps > 0) / count(resolved)`.

## Why exclusions matter

An unresolved outcome is not "a loss" and a proposal with no probability is not "in the 0%
bucket" - both would silently corrupt a calibration curve if counted. This function excludes
them explicitly rather than defaulting them to any value, consistent with this architecture's
"never fabricate missing data" rule.

## Consumers

- **Phase 11 monitoring / drift** - a large realized-win-rate deviation from the bucket's own
  midpoint (e.g. the 0.6-0.7 bucket realizing a 30% win rate) is exactly the kind of signal
  `packages.monitoring.drift.BaselineDriftService.assess()` is designed to receive as
  `current` against a recorded `baseline`.
- **Phase 12 retraining evidence review** - a retrained model's evidence record
  (`EvidenceStatus.INSUFFICIENT`, awaiting human review) is exactly the record a reviewer would
  want a calibration curve attached to before ever considering promotion - promotion itself
  remains a separate, human-gated action regardless of what the curve shows.
