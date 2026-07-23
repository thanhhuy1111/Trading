# Registry Design

`packages/registries/` provides 7 independent `ArtifactRegistry` instances
(`packages/registries/instances.py`): `strategy_registry`, `model_registry`,
`evidence_registry`, `feature_artifact_registry`, `label_registry`, `universe_registry`,
`policy_registry`. Each is a separate object with its own `_entries` dict - a lookup in one can
never accidentally resolve against another's entries.

## Why `feature_artifact_registry`, not `feature_registry`

`packages.features.registry.feature_registry` already exists (Checkpoint 1) - the calculator
registry, where an entry is one implementation (e.g. "rsi_14 v1.0.0"). `feature_artifact_registry`
is a different, higher granularity: a whole named FEATURE SET (e.g. "standard_v1") as a
versioned, checksummed artifact. The two are deliberately not merged - a calculator version
bump and a feature-set version bump are different events with different blast radii.

## `RegistryEntry` (`packages/registries/models.py`)

Exact-match key: `(name, version)` via `.key()`. `is_compatible(symbol, timeframe)` is
exact-match too - an entry scoped to specific symbols/timeframes must match exactly; an entry
with an EMPTY `compatible_symbols`/`compatible_timeframes` list is explicitly universal
(declared, not implied).

## Status state machine

```
DRAFT -> RESEARCH_ONLY -> VALIDATED -> APPROVED -> DEGRADED -> STALE -> DISABLED
                |                          |           |         |
                v                          v           v         v
            REJECTED                   DISABLED   (APPROVED  APPROVED
                                                    or STALE)  (recoverable)
```

Enforced by `packages/registries/registry.py: _ALLOWED_TRANSITIONS` - anything not listed is
rejected (`InvalidStatusTransitionError`), so a caller can never jump straight from `DRAFT` to
`APPROVED`, or resurrect a `REJECTED`/`DISABLED` entry through this path. `DEGRADED` and
`STALE` can both recover to `APPROVED` (a human/monitoring decision, never automatic - see
`docs/operations/DRIFT_AND_AUTOMATIC_ACTIONS.md` for which transitions monitoring is allowed
to make on its own).

## `ArtifactRegistry` API

- `register(entry)` - no transition check on first registration (an entry can be created
  directly in any status, e.g. Phase 12's retraining workflow always creates at `RESEARCH_ONLY`).
- `get(name, version)` - exact match only, no "latest" fallback.
- `transition_status(name, version, new_status, reason_codes)` - enforces the state machine.
- `find_compatible(symbol, timeframe, status)` - the only "fuzzy" lookup this registry
  supports, and it's explicit compatibility matching, not similarity matching.
- `all_entries()`.

## Who uses which registry today

- `model_registry` - Phase 12's `RetrainingWorkflow` publishes every trained model here,
  always `RESEARCH_ONLY`.
- `strategy_registry`, `feature_artifact_registry`, `label_registry`, `universe_registry`,
  `policy_registry`, `evidence_registry` - wired and tested (`tests/unit/test_registries.py`),
  available for the next campaign to populate; none is required to be non-empty for the
  architecture to run correctly.
