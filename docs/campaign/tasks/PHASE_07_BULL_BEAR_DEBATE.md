# Phase 07 — Bull–Bear Debate

## Status

**COMPLETE**

## Architecture and safety

- Fixed maximum of two rounds; constructor cannot configure a larger loop.
- Distinct Bull/Bear prompts carry an exact assigned side and outputs must match it.
- Inputs are immutable evidence records from the current analysis only; stale, invalid,
  missing and future evidence fail before any provider call.
- Numeric claims must exactly match cited evidence; every accepted argument has at least one
  invalidating condition.
- Later same-side rounds must add evidence; normalized summary duplicates are also rejected.
- Transcript is append-only, contains per-turn model/prompt/token/latency telemetry, and is
  reserved before provider calls. Completed reruns return the same transcript.
- `COMPLETE` requires accepted evidence from both sides. One-sided success is `PARTIAL` with
  failure reasons; no valid side is `FAILED`.

## Verification

- Offline debate tests: 6 passed.
- Full pytest: 566 passed, 12 skipped, 1 known Alembic failure.
- Ruff and `git diff --check`: clean.
- Mypy baseline: 180 errors in 67 files.
- Independent review findings were fixed; final re-review has no remaining
  CRITICAL/HIGH/MEDIUM findings.

No network provider, private exchange API, execution path or live-trading flag is used.
