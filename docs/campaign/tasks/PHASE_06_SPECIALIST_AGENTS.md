# Phase 06 — Specialist Agents

## Status

**COMPLETE**

## Research and reused boundaries

Phase 6 reuses the Phase 4E approval-service-backed `XGBoostRuntime`, the Phase 5
`StructuredLLMProvider`/Prompt Registry, and immutable contracts. Technical and derivatives
agents receive only precomputed, versioned evidence snapshots. They never receive candles or
calculate indicators.

## Architecture

- Evidence is append-only, analysis-scoped, timezone-aware and lookahead checked.
- Technical, derivatives and quantitative schemas have exact names, units, domains,
  feature-set versions and a single snapshot source.
- Technical interpretation requires the complete technical snapshot and deterministic
  quantitative evidence produced by one approved runtime prediction.
- Derivatives interpretation requires the complete raw/derived derivatives schema.
- Every LLM numeric claim must exactly match an evidence ID, name, value and unit; digits in
  free text are rejected.
- Provider errors and invalid output return `UNAVAILABLE` without fabricated fields.
- Quantitative Agent is code-only and invokes an exact `XGBoostRuntime` backed by an exact
  `ApprovedModelRepository`; it publishes probability evidence from the returned prediction.

## Acceptance

- [x] Unified immutable agent contracts.
- [x] Every numeric claim is evidence-bound.
- [x] Invalid, stale, future, incomplete, duplicated or mixed-source evidence fails closed.
- [x] Provider unavailable/exception is safe.
- [x] Quantitative output cannot be caller-supplied or loaded from an arbitrary repository.
- [x] Tests are offline and contain no real provider call.
- [x] No live trading, private API or order path was added.

## Verification

- Specialist/runtime focused tests: 13 passed.
- Full pytest: 560 passed, 12 skipped, 1 known Alembic failure.
- Ruff: clean.
- Mypy: 180 errors in 67 files, unchanged baseline.
- Independent review: no CRITICAL/HIGH/MEDIUM findings after fixes.

Synthetic fixtures validate contracts only. They are not market evidence and create no
persistent approved model.
