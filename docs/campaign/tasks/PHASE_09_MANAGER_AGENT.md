# Phase 09 — Manager Agent

## Status

**COMPLETE**

## Architecture

- Deterministic Manager consumes exactly three specialist assessments, complete debate,
  Verification and Risk results for one analysis/time.
- It re-runs the exact Verification authority against canonicalized inputs and requires the
  supplied result to match.
- Risk results are issued by an exact Risk Engine bound to the same Verification authority;
  the engine retains the risk-result → verification-result digest relationship.
- Any unavailable/mismatched/untrusted/rejected upstream yields `NO_DECISION` with no
  direction, confidence, risk level, evidence or invalidation claims.
- Valid decisions use deterministic majority direction with quantitative tie-break, verified
  quantitative confidence and verified evidence. Specialist plus accepted debate invalidation
  conditions are retained.
- SHORT is schema-disabled; bearish synthesis safely returns `NO_DECISION`.
- Immutable snapshots are append-only and idempotent under canonical assessment ordering.

## Verification

- Manager + verification/risk focused tests: 7 passed.
- Full pytest: 573 passed, 12 skipped, 1 known Alembic failure.
- Ruff/diff: clean.
- Mypy remains 180 errors in 67 files (baseline).
- Independent review: no remaining CRITICAL/HIGH/MEDIUM findings after fixes.

No LLM can override rule gates. No execution, private API or live-trading behavior was added.
