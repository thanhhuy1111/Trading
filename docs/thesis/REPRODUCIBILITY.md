# Reproducibility Guide

Status: **PROCEDURE READY — CONFIRMATORY RUN PENDING EVIDENCE**

## Required provenance

Archive these items for every confirmatory run:

- exact Git commit SHA and clean-tree status;
- Python and Node versions;
- dependency lockfile checksums;
- public/licensed source identifiers and license grants;
- raw-input, dataset, evidence, configuration, prompt, and model checksums;
- temporal folds, horizons, seeds, and approval decisions;
- complete experiment/outcome JSONL export and manifest;
- test, static-analysis, dashboard-build, and safety-flag output.

Local credentials, caches, private DSNs, and research market data are never committed.

## Environment

From the repository root:

```bash
uv sync --frozen
.venv/bin/python --version
node --version
git rev-parse HEAD
git status --short
```

If `uv.lock` is not part of the committed revision, use the repository's documented
environment bootstrap and record the resolved dependency manifest separately. Do not
silently generate a new dependency set for a confirmatory run.

## Verification

```bash
.venv/bin/pytest tests/ -q
.venv/bin/ruff check .
.venv/bin/mypy packages/ apps/
cd apps/dashboard
npm test -- --run
npm run build
npm audit
```

Known baseline failures must be named; they may not be hidden by deleting or weakening tests.

## Experimental capture

Validate the frozen machine-readable protocol and materialize its exact schedule:

```bash
.venv/bin/python -m packages.experiments.thesis_protocol validate \
  --protocol configs/research/thesis_protocol_v1.json
.venv/bin/python -m packages.experiments.thesis_protocol schedule \
  --protocol configs/research/thesis_protocol_v1.json \
  --output artifacts/thesis/protocol_v1_schedule.json
```

The validator accepts only the pinned protocol-v1 digest and prints its canonical SHA-256; a
mutated schema-v1 copy fails. The schedule command writes `thesis_schedule_v1` through a
same-directory, fsynced temporary file, atomic no-replace link, and directory fsync. It records
the same checksum, every UTC clock, variant count, and planned-attempt count. Re-running
against the same output path must fail.

The collection runner must then:

1. Record the clean source SHA, protocol/schedule checksums, locked model fields, dependency
   lock checksum, configuration checksums, and safety flags.
2. At every schedule clock, run all ten protocol variants from the same checksum-verified
   point-in-time snapshot.
3. Persist append-only `experiment_record_v1` envelopes before outcome maturity.
4. Append `experiment_outcome_v1` only at or after `as_of_time + 4h`.
5. Export canonical JSONL to a new path with the Phase 13 no-clobber exporter.
6. Validate that schedule clocks × ten variants reconcile with complete/unavailable/rejected
   manifest counts and that all joins preserve row cardinality.
7. Retain attempted, unavailable, rejected, and completed records.
8. Run the frozen endpoint/contrast definitions from the protocol and archive code, logs,
   tables, raw denominators, and checksums.

No production collection CLI currently wires all ten variants. In particular, production
Manager and Risk require Verification and cannot be reused for the no-Verification ablation.
The locked configuration therefore sets `collection_may_start=false` and requires a separately
versioned, reviewed, no-action research adapter. This is a declared prerequisite before the
study can move from `PENDING_EVIDENCE`; the validator and schedule CLI deliberately do not
fabricate cohort rows.

## Determinism and seeds

Every stochastic library seed, data-loader order, thread/process setting, and hardware/runtime
identifier used by a confirmatory run must be recorded. A rerun may differ because of provider
or hardware nondeterminism; such differences are reported rather than concealed.

## Result publication checklist

- [ ] Cohort acceptance gate passed.
- [ ] Source and license audit passed.
- [ ] No future or stale evidence entered an eligible row.
- [ ] All denominators reconcile with manifest counts.
- [ ] Statistical plan predates the analyzed outcomes.
- [ ] Paper results are visibly labeled simulated.
- [ ] Tables contain only values computed from the archived export.
- [ ] Independent reviewer verified claims against artifacts.

Until all boxes are supported by archived evidence, results remain `PENDING_EVIDENCE`.
