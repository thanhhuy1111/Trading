# Domain Model

`packages/domain/entities.py` is the single place that lists "the domain model" - it
re-exports stable entities that already existed before this campaign (never duplicating them)
and defines every entity that has no Checkpoint 1/2 equivalent.

## Re-exported (pre-existing, canonical elsewhere)

| Name in `packages.domain.entities` | Canonical source |
|---|---|
| `RegimeAssessment` | `packages.agents.regime.RegimeResult` |
| `MarketDataset` | `packages.backtest.models.HistoricalDatasetDefinition` |
| `TradeCandidate` | `packages.candidates.models.TradeCandidate` |
| `EvidenceRecord` | `packages.evidence.models.EvidenceRecord` |
| `FeatureSnapshot` | `packages.features.models.FeatureSnapshot` |
| `StrategyRoute` | `packages.governance.strategy_router.RoutingDecision` |
| `DatasetQualityReport` | `packages.market_data.historical_quality.DatasetQualityReport` |

## Defined fresh in Phase 1

Every fresh entity carries `version`, `created_at`, and `reason_codes` at minimum; most carry
source/lineage identifiers and a `status` where a lifecycle applies.

- **`AgentAssessment`** - one agent's contribution to a decision point (agent_id, confidence,
  adjusted_confidence, approved_for_aggregation).
- **`CandidateOutcome`** - the realized-outcome half of a `TradeCandidate`'s lifecycle
  (gross/net return, exit_reason, meta_label ACCEPT/REJECT).
- **`ModelPrediction`** - a `MetaLabelService`'s output (`probability=None` is the honest,
  required baseline value - never fabricated).
- **`MarketContextAssessment`** - one LLM/context agent's output; the schema every LLM agent
  (Phase 9) must produce (see `docs/llm/LLM_AGENT_FRAMEWORK.md`).
- **`RankingResult`** - `BaselineRankingService`'s output per candidate, with the individual
  weighted terms broken out (`evidence_weight`, `cost_penalty`, etc.) for auditability.
- **`CorrelationSnapshot`** - `correlation: Optional[Decimal] = None` (never 0.0 for
  missing/insufficient data).
- **`PortfolioRiskDecision`** - `decision` (APPROVE/REDUCE/REJECT/HALT),
  `requested_risk_pct`/`approved_risk_pct`, `policy_version`, `reason_codes`.
- **`TradeProposal`** - the recommendation runtime's output entity; carries
  `application_result_state` on every instance.
- **`ShadowProposal`** - `model_config = {"frozen": True}`; immutable snapshot with a
  `compute_checksum()` method (see `docs/shadow/SHADOW_MODE.md`).
- **`ShadowOutcome`** - the evaluated result of a `ShadowProposal`
  (BARRIER_EXIT/TIMEOUT_EXIT/DATA_UNAVAILABLE/PENDING).
- **`DriftAssessment`** - `severity: DriftSeverity`, `baseline_value`/`current_value` both
  `Optional` (missing data is its own explicit case, never silent "no drift").
- **`ReadinessStatus`** - the six-axis entity; see `docs/architecture/READINESS_AXES.md`.

## Helper

`stable_checksum(payload: Dict[str, Any]) -> str` - deterministic SHA-256 over sorted-key JSON,
shared by every entity that needs a reproducible checksum without reimplementing it slightly
differently each time.

## Enums

All in `packages/domain/enums.py`, `str, Enum` throughout (never a free-form string for a
critical state): the six readiness enums, plus `DatasetQualityLevel`, `CandidateStatus`,
`EvidenceLookupResult`, `RegistryEntryStatus`, `ModelType`, `MetaLabelDecision`,
`MarketContextStatus`, `RankingStatus`, `PortfolioRiskDecisionType`, `ApplicationResultState`
(11 values - see `docs/runtime/RECOMMENDATION_RUNTIME.md`), `ShadowProposalKind`,
`ShadowOutcomeStatus`, `DriftSeverity`, `LLMAgentStatus`.
