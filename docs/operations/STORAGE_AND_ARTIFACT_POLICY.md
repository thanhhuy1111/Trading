# Storage and Artifact Policy

What this campaign commits to git, and what it deliberately never does.

## Never committed

- Downloaded OHLCV candle data (`data/research/candles/*.json` - gitignored; read by
  `packages.runtime.candles_cache.cached_candles_provider` and
  `packages.research.data_fetcher`, but never checked in).
- Large candidate CSVs or dry-run intermediate artifacts.
- Trained model binaries or large weight files. Phase 12's retraining workflow keeps its
  logistic-regression artifact small enough to embed inline as JSON
  (`artifact_location=f"inline://{job_id}"` in the model registry) rather than writing a
  separate large file - a future campaign with a genuinely large model (a gradient-boosted
  tree ensemble, a neural network) must not commit its weights to this repository; it should
  reference an external artifact store instead.
- Large shadow-mode outcome datasets. `packages.shadow.service.InMemoryShadowStore` is
  in-process only; a production deployment drains it to a database, not to committed files.
- Secrets, API keys, credentials of any kind.

## Committed

- Schemas, manifests, checksums (the domain entities in `packages/domain/entities.py`, the
  registry entries in `packages/registries/`, the evidence keys in `packages/evidence/models.py`).
- Small, deterministic fixtures used by tests (inline in the test files themselves - see
  `tests/unit/`, `tests/acceptance/` - never a separately-downloaded fixture file).
- Policy documents (this directory, `docs/governance/`, `docs/architecture/`).
- Summary reports with real, computed numbers (`docs/research/REAL_CANDIDATE_DRY_RUN_REPORT.md`,
  `docs/research/SPACING_DIAGNOSTICS.json`, `docs/ARCHITECTURE_COMPLETION_REPORT.md`) - these
  are small, text-based, and reproducible by re-running the script that produced them.

## Retention

- **Evidence records** - retained indefinitely by default (they're the audit trail); a
  `DISABLED`/`REJECTED` record is never deleted, only status-transitioned, so the history of
  "this was tried and didn't clear the gate" is never lost.
- **Shadow proposals/outcomes** - production wiring should retain these at least as long as the
  evidence records they informed, so a calibration curve can always be reconstructed.
- **Audit log** (`packages.evidence.audit.EvidenceAuditLog`) - append-only by design; the
  in-memory implementation used in tests is not a retention policy, it's a test convenience -
  production wiring drains it into `packages.audit.repository.AuditRepository` (Postgres-backed,
  pre-existing).
- **Registry entries** - never deleted, only status-transitioned (see
  `docs/architecture/REGISTRY_DESIGN.md`'s state machine) - a `DISABLED` model version stays
  queryable for post-incident review.

## Why this matters for reproducibility

Every number in `docs/research/REAL_CANDIDATE_DRY_RUN_REPORT.md` and this campaign's test
suite is reproducible from the checked-in code plus a fresh data fetch - nothing depends on a
committed, possibly-stale binary blob. This is also why `packages.runtime.candles_cache`
returns an empty candle list (not an error) for a missing cache file: the architecture must run
correctly - producing `NO_CANDIDATE`, never a crash - in a fresh clone that hasn't run the data
fetch yet.
