# Phase 08 — Verification & Risk

## Status

**COMPLETE**

## Architecture

- Code-only Verification Agent has veto authority and requires one unique AVAILABLE
  Technical, Derivatives and Quantitative assessment plus a complete two-sided debate.
- Every assessment/debate evidence ID is re-resolved against current analysis, status and
  availability time; every numeric claim is re-matched by ID/name/value/unit.
- Quantitative confidence and technical volatility are extracted from their verified evidence
  records. Neither can be supplied by the risk caller.
- Code-only Risk Engine binds the verification timestamp/analysis, uses conservative slippage
  entry for both reward/risk and sizing, and independently vetoes invalid stop, insufficient
  reward/risk, volatility, drawdown, exposure and sizing.
- Risk schema is explicitly LONG-only for this checkpoint. SHORT remains disabled until its
  distinct sizing/stop/slippage/accounting rules meet the later paper-trading gate.

## Verification

- Phase-focused verification/existing governor tests: 24 passed.
- Full pytest: 569 passed, 12 skipped, 1 known Alembic failure.
- Ruff and diff check: clean.
- Mypy remains 180 errors in 67 files (baseline).
- Independent review: no remaining CRITICAL/HIGH/MEDIUM findings after fixes.

No LLM performs a risk calculation. No execution, private API or live-trading path was added.
