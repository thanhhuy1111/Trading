# Phase 13 — Experimental Data Collection

Status: **COMPLETE**

## Delivered

- Immutable experimental envelope for raw/normalized inputs, features, evidence, exact
  model/prompt versions, agent outputs, debate, Verification, Risk, Manager, actual outcomes,
  simulated PnL, token usage, latency, retries/errors and data quality.
- Reproducible SHA-256 experiment identity bound to point-in-time inputs and versions.
- Locked append-only store with exact-replay idempotency, sequence and payload conflict checks.
- Separate append-only horizon outcome events with strict availability/observation time,
  preserving the original decision envelope while outcomes mature.
- Canonical JSONL export using fsync/atomic rename; existing exports are never overwritten.
- Explicit 365-day manual-audited retention policy, deterministic expiry candidates and a
  field-level data dictionary.
- Honest aggregate report for observed prediction/trading metrics, disagreement, Verification
  rejection, comparable cost, nearest-rank latency and explicit missing-data denominators.
  Trading metrics require an explicit horizon cohort and comparable PnL currency.

## Acceptance and safety

- Focused tests: 5 passed.
- Full suite: 594 passed, 12 skipped, 1 known Alembic failure.
- Targeted Ruff: clean.
- Targeted mypy: clean.
- Nested secret-like keys and credential-bearing DSNs fail before persistence.
- Missing outcomes/costs are null and excluded from denominators; they are never fabricated as
  zero, false or successful.
- Canonical payloads accept only deterministic JSON-compatible types; direct constructors
  revalidate secret absence, canonical form and checksum.
- UTC-normalized IDs, canonical horizon aliases and free-text credential patterns prevent
  equivalent-time drift, duplicate cohorts and bearer/provider-key leakage.
- Synthetic tests validate contracts only and are not experimental performance results.
