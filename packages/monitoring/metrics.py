"""Phase 11: the 20 named metrics this architecture reports. Each is just a stable string
name recorded through `MonitoringService.record_metric` - no metric here claims a target or
threshold implies profitability; thresholds live in `packages.monitoring.drift` and
`packages.monitoring.evidence_lifecycle`, not here."""

# --- Data / pipeline health ---
CANDLES_INGESTED_TOTAL = "candles_ingested_total"
DATA_QUALITY_REJECTED_TOTAL = "data_quality_rejected_total"
STALE_DATA_EVENTS_TOTAL = "stale_data_events_total"

# --- Candidate generation ---
CANDIDATES_GENERATED_TOTAL = "candidates_generated_total"
ROUTER_NO_TRADE_TOTAL = "router_no_trade_total"
NO_TRADE_EVENTS_TOTAL = "no_trade_events_total"

# --- Meta-label / model ---
MODEL_NOT_AVAILABLE_TOTAL = "model_not_available_total"
META_LABEL_REJECTED_TOTAL = "meta_label_rejected_total"

# --- Evidence ---
EVIDENCE_LOOKUPS_TOTAL = "evidence_lookups_total"
EVIDENCE_MISMATCH_TOTAL = "evidence_mismatch_total"
EVIDENCE_MISSING_TOTAL = "evidence_missing_total"
EVIDENCE_STALE_TOTAL = "evidence_stale_total"

# --- Ranking / proposals ---
PROPOSALS_RESEARCH_TOTAL = "proposals_research_total"
PROPOSALS_APPROVED_TOTAL = "proposals_approved_total"

# --- Portfolio risk ---
RISK_REJECTED_TOTAL = "risk_rejected_total"
RISK_HALTED_TOTAL = "risk_halted_total"
RISK_REDUCED_TOTAL = "risk_reduced_total"

# --- Shadow mode ---
SHADOW_PROPOSALS_RECORDED_TOTAL = "shadow_proposals_recorded_total"
SHADOW_OUTCOMES_EVALUATED_TOTAL = "shadow_outcomes_evaluated_total"

# --- System ---
SYSTEM_DEGRADED_EVENTS_TOTAL = "system_degraded_events_total"

ALL_METRIC_NAMES = frozenset({
    CANDLES_INGESTED_TOTAL, DATA_QUALITY_REJECTED_TOTAL, STALE_DATA_EVENTS_TOTAL,
    CANDIDATES_GENERATED_TOTAL, ROUTER_NO_TRADE_TOTAL, NO_TRADE_EVENTS_TOTAL,
    MODEL_NOT_AVAILABLE_TOTAL, META_LABEL_REJECTED_TOTAL,
    EVIDENCE_LOOKUPS_TOTAL, EVIDENCE_MISMATCH_TOTAL, EVIDENCE_MISSING_TOTAL, EVIDENCE_STALE_TOTAL,
    PROPOSALS_RESEARCH_TOTAL, PROPOSALS_APPROVED_TOTAL,
    RISK_REJECTED_TOTAL, RISK_HALTED_TOTAL, RISK_REDUCED_TOTAL,
    SHADOW_PROPOSALS_RECORDED_TOTAL, SHADOW_OUTCOMES_EVALUATED_TOTAL,
    SYSTEM_DEGRADED_EVENTS_TOTAL,
})
# Exactly 20 named metrics (Section 15) - tests/unit/test_monitoring.py asserts this count so
# it can't silently drift as metrics are added or renamed.
