"""Phase 10: builds the immutable `ShadowProposal` snapshot from a `TradeProposal` plus
whatever upstream-stage snapshots the caller has in hand. Every snapshot field defaults to an
honest empty value (`{}` / `[]`) rather than being required - the schema (Dict[str, Any]) never
demands data a caller doesn't have, but it also never fabricates a substitute."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from packages.domain.entities import ShadowProposal
from packages.domain.enums import ApplicationResultState, ShadowProposalKind

_KIND_BY_RESULT_STATE = {
    ApplicationResultState.APPROVED_PROPOSAL: ShadowProposalKind.APPROVED_SHADOW,
    ApplicationResultState.RESEARCH_PROPOSAL: ShadowProposalKind.RESEARCH_SHADOW,
}


def shadow_kind_for_application_result_state(state: ApplicationResultState) -> Optional[ShadowProposalKind]:
    """Only APPROVED_PROPOSAL and RESEARCH_PROPOSAL ever produce a TradeProposal (Phase 7) -
    every other state already has no proposal to shadow. Returns None for anything else so a
    caller never guesses a shadow kind for a state that structurally can't have one."""
    return _KIND_BY_RESULT_STATE.get(state)


def build_shadow_proposal(
    proposal: Any,  # packages.domain.entities.TradeProposal
    *,
    market_data_timestamp: datetime,
    code_commit: str = "n/a",
    configuration_versions: Optional[Dict[str, str]] = None,
    feature_snapshot: Optional[Dict[str, Any]] = None,
    regime_snapshot: Optional[Dict[str, Any]] = None,
    agent_assessments_snapshot: Optional[List[Dict[str, Any]]] = None,
    meta_label_snapshot: Optional[Dict[str, Any]] = None,
    market_context_snapshot: Optional[List[Dict[str, Any]]] = None,
    evidence_snapshot: Optional[Dict[str, Any]] = None,
    ranking_snapshot: Optional[Dict[str, Any]] = None,
    correlation_snapshot: Optional[Dict[str, Any]] = None,
    portfolio_risk_snapshot: Optional[Dict[str, Any]] = None,
    prediction_horizon_bars: int = 1,
    label_version: str = "volatility_band_1bar_v1",
    label_threshold_return: Optional[Decimal] = None,
    label_threshold_source: Optional[str] = None,
) -> ShadowProposal:
    kind = shadow_kind_for_application_result_state(proposal.application_result_state)
    if kind is None:
        raise ValueError(
            f"application_result_state={proposal.application_result_state} has no valid shadow kind "
            "(only APPROVED_PROPOSAL and RESEARCH_PROPOSAL produce a TradeProposal to shadow)."
        )

    if prediction_horizon_bars <= 0:
        raise ValueError("prediction_horizon_bars must be positive")
    evidence = evidence_snapshot or {}
    if label_threshold_return is not None:
        source = (
            evidence.get(label_threshold_source)
            if label_threshold_source is not None
            and label_threshold_source == label_threshold_source.strip()
            else None
        )
        if (
            not label_threshold_return.is_finite()
            or label_threshold_return < 0
            or not isinstance(source, dict)
            or source.get("label_version") != label_version
            or source.get("horizon_bars") != prediction_horizon_bars
            or Decimal(str(source.get("threshold_return")))
            != label_threshold_return
        ):
            raise ValueError("label threshold must match captured evidence metadata")
    candidate_snapshot = proposal.model_dump(mode="json")
    candidate_snapshot["prediction_horizon_bars"] = prediction_horizon_bars
    candidate_snapshot["label_version"] = label_version
    candidate_snapshot["label_threshold_return"] = (
        str(label_threshold_return) if label_threshold_return is not None else None
    )
    candidate_snapshot["label_threshold_source"] = label_threshold_source
    draft = ShadowProposal(
        kind=kind,
        proposal_id=proposal.proposal_id,
        candidate_snapshot=candidate_snapshot,
        feature_snapshot=feature_snapshot or {},
        regime_snapshot=regime_snapshot or {},
        agent_assessments_snapshot=agent_assessments_snapshot or [],
        meta_label_snapshot=meta_label_snapshot or {},
        market_context_snapshot=market_context_snapshot or [],
        evidence_snapshot=evidence,
        ranking_snapshot=ranking_snapshot or {},
        correlation_snapshot=correlation_snapshot,
        portfolio_risk_snapshot=portfolio_risk_snapshot or {},
        market_data_timestamp=market_data_timestamp,
        code_commit=code_commit,
        configuration_versions=configuration_versions or {},
    )
    return draft.model_copy(update={"checksum": draft.compute_checksum()})
