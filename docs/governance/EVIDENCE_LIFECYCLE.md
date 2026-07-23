# Evidence Lifecycle (Phase 5)

`packages/evidence/` is the exact-match asset/timeframe/model evidence binding introduced in
Checkpoint 1 and extended here with a full typed lookup result and audit trail.

## `EvidenceKey` - the exact-match tuple

`NamedTuple` with 12 fields, every one participating in equality: `strategy_name`,
`strategy_version`, `symbol`, `timeframe`, `model_type`, `model_version`, `feature_version`,
`label_version`, `dataset_checksum`, `gate_version`, `config_hash`, `code_commit`. There is no
normalization, fuzzy matching, or partial-key fallback - a result on BTC/USDT 1D says nothing
about ETH/USDT 1D, BTC/USDT 4h, or the same strategy under a different `model_version`.

## `EvidenceStatus` (8 values)

`UNIVERSAL_APPROVED`, `ASSET_SPECIFIC_APPROVED`, `RESEARCH_ONLY`, `INSUFFICIENT`, `REJECTED`,
`STALE`, `DEGRADED`, `DISABLED`. `DEGRADED` and `DISABLED` were added in this campaign (Phase
5) to the canonical enum in `packages/evidence/models.py` - not duplicated elsewhere; a
duplicate-enum bug introduced mid-campaign was caught and fixed the same session (see
`packages/domain/entities.py`'s re-export table, which imports `EvidenceStatus` from
`packages.evidence.models`, never redefines it).

## `EvidenceLookupResult` (5 values)

`MATCH`, `MISMATCH`, `MISSING`, `STALE`, `DISABLED` - returned by
`EvidenceStore.lookup_with_result()`. `MISMATCH` is distinct from `MISSING`: it means a record
exists for this exact `(strategy_name, symbol, timeframe)` but not for this exact
`model_version`/`config_hash`/etc. - the case the exact-match rule exists to catch, e.g. a
caller silently reusing an old model version's evidence.

## Audit events (6)

`packages/evidence/audit.py`: `evidence_created`, `evidence_updated`, `evidence_degraded`,
`evidence_staled`, `evidence_disabled`, `lookup_rejected`. Every non-`MATCH` lookup outcome is
recorded as `lookup_rejected` - a rejected lookup is exactly as auditable as a granted one.
`EvidenceAuditLog` is in-memory (offline-testable by default), designed to drain into the
existing DB-backed `packages.audit.repository.AuditRepository` for production.

## `is_actionable`

True only for a fresh, exact-match `APPROVED` record (`UNIVERSAL_APPROVED` or
`ASSET_SPECIFIC_APPROVED`). Every other outcome - missing, `RESEARCH_ONLY`, `INSUFFICIENT`,
`REJECTED`, `STALE`, `DEGRADED` - blocks a trade proposal from becoming capital-backed. This is
exactly the boolean `packages.runtime.recommendation_service` uses to decide
`APPROVED_PROPOSAL` vs. `RESEARCH_PROPOSAL`.

## Automatic transitions

See `docs/operations/DRIFT_AND_AUTOMATIC_ACTIONS.md` - `APPROVED -> DEGRADED -> DISABLED` is
the only direction Phase 11's monitoring can push a record automatically; nothing in this
codebase can move a record back toward `APPROVED` without a human action.
