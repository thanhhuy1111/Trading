# Phase 15 — Research and Thesis Package

Status: **COMPLETE AS THESIS-READY STRUCTURE; RESULTS PENDING EVIDENCE**

## Scope and evidence decision

The repository has real historical alpha-research artifacts, but not a complete, time-matured
end-to-end cohort for all ten required quantitative/multi-agent ablations. Phase 15 therefore
implements the playbook's insufficient-data path. It does not claim empirical completion.

## Delivered

- Thesis-ready structure with all required academic sections.
- Point-in-time paired methodology and explicit cohort eligibility.
- Pre-registration protocol for all ten required variants.
- Thesis-specific data dictionary layered on the canonical experimental schema.
- Reproducibility and publication checklist.
- Checked Python dependency lockfile for a frozen environment.
- Executable digest/schedule validator, durable no-clobber publisher, versioned thesis identity
  model and calendar-block helpers.
- One explicit `PENDING_EVIDENCE` row for every required comparison.
- Clear separation of historical backtests, shadow observations, simulated paper outcomes,
  and unavailable live performance.

## Architecture decisions

- Confirmatory protocol/configuration checksums must predate outcomes.
- Variant input parity is required; repeated horizons remain separate cohorts.
- Unavailable and rejected records remain visible in denominators.
- No statistical method, sample size, metric value, or conclusion is invented.
- Dynamic weighting remains research-only and Verification omission cannot create authority.

## Safety

No provider, exchange endpoint, order path, model promotion, production prompt/weight mutation,
credential, market record, citation, confidence, probability, or empirical result was added.
Live trading and private exchange APIs remain disabled.

## Verification

- Thesis package tests: 16 passed.
- Full suite: 621 passed, 12 skipped, 1 known missing-Alembic-config failure.
- Full Ruff: clean.
- Targeted mypy: clean.
- Full mypy: 202 errors in 71 files, tracked campaign-wide debt; targeted Phase 15 mypy clean.
- `uv lock --check`: passed.

The analysis protocol is digest-locked and schedulable, but correctly keeps
`collection_may_start=false` until a separately versioned research-only ablation adapter is
implemented. No experimental row was generated.

Independent review must find no remaining Critical, High, or Medium issue before the checkpoint
is committed.

Final independent read-only review found no remaining Critical, High, or Medium issue. The
reviewer did not edit files.

## Next task

Campaign-level final acceptance and `docs/campaign/FINAL_CAMPAIGN_REPORT.md`.
