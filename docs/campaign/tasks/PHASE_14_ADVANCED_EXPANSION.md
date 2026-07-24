# Phase 14 — Advanced Expansion

Status: **COMPLETE (SAFE-UNAVAILABLE BY DEFAULT)**

## Delivered

- One audited provider protocol and fail-closed service for News, On-chain, Macro, Sentiment
  and Market Regime sources.
- Every accepted observation requires exact provider/version, auditable license ID, symbol,
  observation/availability/receipt times, healthy data quality and immutable values.
- License grants bind provider/source kind to allowed provenance domains, research permission,
  retention and redistribution terms. Unknown licenses/domains fail closed.
- Each source kind has an exact schema, source record ID, source event/release/window time and
  unit/range checks; generic or mislabeled payloads are rejected.
- Future, degraded, mismatched, disabled, unconfigured, invalid and provider-error states
  produce `UNAVAILABLE` with no evidence.
- Advanced evidence persists the full three-clock lineage, provenance and license, has a
  self-validating UTC-normalized identity and an idempotent locked registry.
- A bounded coordinator runs the exact five-agent research set and returns an immutable bundle
  with `production_authority=False`; disabled agents remain explicit unavailable assessments.
- Exact BTC/ETH model bindings; ETH resolution is unavailable while its flag is off and never
  falls back to a BTC model.
- Reflection and dynamic-weight artifacts are immutable research-only proposals. Literal
  schemas forbid production mutation and require a separate approval gate.
- Eight feature flags default false: five sources, ETH, Reflection and dynamic weights.

No external provider credential was configured. The provider contracts and mock tests are
complete; real News/On-chain/Macro/Sentiment/Regime data remains unavailable rather than
fabricated.

## Verification and safety

- Focused tests: 11 passed.
- Full suite: 605 passed, 12 skipped, 1 known missing-Alembic-config failure.
- Targeted Ruff and mypy: clean.
- Tests cover all five source kinds, disabled/unconfigured/malformed/future-received/degraded/
  unlicensed rejection, evidence registration, coordinator output, ETH isolation and research
  proposal gates.
- No private exchange API, live trading, prompt mutation, production weight mutation,
  automatic model promotion or unlicensed source was added.
