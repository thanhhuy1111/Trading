# The Six Readiness Axes

`packages/domain/entities.py: ReadinessStatus` reports six independent axes
(`packages/domain/enums.py`). They must never be conflated - "the architecture runs" is a
completely different claim from "a strategy is approved to trade," and this system keeps them
as six separate enums on one entity specifically so no single boolean can blur that line.

| Axis | Enum | Values | What it answers |
|---|---|---|---|
| `architecture_readiness` | `ArchitectureReadiness` | `NOT_READY` / `PARTIAL` / `READY` | Does the full pipeline (universe -> ... -> readiness) run end-to-end, including every safe-rejection path, without raising? |
| `strategy_readiness` | `StrategyReadiness` | `NOT_READY` / `RESEARCH_ONLY` / `ASSET_SPECIFIC_APPROVED` / `UNIVERSAL_APPROVED` | Has any strategy cleared the evidence promotion gate, and how broadly? |
| `model_readiness` | `ModelReadiness` | `NOT_AVAILABLE` / `BASELINE` / `RESEARCH_ONLY` / `APPROVED` | Is a trained model even registered, vs. the pass-through/heuristic baseline actually in use? |
| `evidence_readiness` | `EvidenceReadiness` | `EMPTY_REGISTRY` / `NO_APPROVED_STRATEGY` / `ASSET_SPECIFIC_EVIDENCE` / `UNIVERSAL_EVIDENCE` | What does the evidence store actually contain right now? |
| `shadow_readiness` | `ShadowReadiness` | `NOT_READY` / `READY` / `ACTIVE` | Can shadow mode record and evaluate proposals? |
| `live_readiness` | `LiveReadiness` | `DISABLED` (only value implemented) | Is live trading enabled? Always `DISABLED` in this codebase - enabling it is an out-of-scope, manual, human decision. |

## The expected state after this campaign

```
ArchitectureReadiness = READY
StrategyReadiness     = RESEARCH_ONLY   (or NOT_READY, depending on what's registered)
ModelReadiness        = BASELINE        (PassThroughMetaLabelService is what's actually wired)
EvidenceReadiness     = EMPTY_REGISTRY or NO_APPROVED_STRATEGY (no campaign has produced APPROVED evidence yet)
ShadowReadiness       = READY
LiveReadiness         = DISABLED
```

`ArchitectureReadiness = READY` and `EvidenceReadiness = EMPTY_REGISTRY` at the same time is
not a contradiction - it is exactly the point of having six axes. The pipeline is fully wired
and tested; nothing has earned the right to trade real capital yet. A future accuracy campaign
changes `StrategyReadiness`/`ModelReadiness`/`EvidenceReadiness` without touching
`ArchitectureReadiness` at all.

## Where readiness is computed

- `packages/runtime/recommendation_service.py: BaselineRecommendationService._readiness_status`
  - a per-call, per-symbol-scoped snapshot returned on every `RecommendationResult`.
- `packages/monitoring/service.py: BaselineMonitoringService.current_readiness`
  - a system-wide snapshot read live from the injected `EvidenceStore`.
- `apps/api/routers/recommendations.py: GET /readiness`
  - the same logic as the monitoring service, exposed over HTTP.

All three read live from the evidence store rather than caching a summary, so none of them can
drift from reality or from each other.
