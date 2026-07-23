"""Phase 10: builds the immutable `ShadowProposal` snapshot from a `TradeProposal` plus
whatever upstream-stage snapshots the caller has in hand. Every snapshot field defaults to an
honest empty value (`{}` / `[]`) rather than being required - the schema (Dict[str, Any]) never
demands data a caller doesn't have, but it also never fabricates a substitute."""

from datetime import datetime
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
) -> ShadowProposal:
    kind = shadow_kind_for_application_result_state(proposal.application_result_state)
    if kind is None:
        raise ValueError(
            f"application_result_state={proposal.application_result_state} has no valid shadow kind "
            "(only APPROVED_PROPOSAL and RESEARCH_PROPOSAL produce a TradeProposal to shadow)."
        )

    draft = ShadowProposal(
        kind=kind,
        proposal_id=proposal.proposal_id,
        candidate_snapshot=proposal.model_dump(mode="json"),
        feature_snapshot=feature_snapshot or {},
        regime_snapshot=regime_snapshot or {},
        agent_assessments_snapshot=agent_assessments_snapshot or [],
        meta_label_snapshot=meta_label_snapshot or {},
        market_context_snapshot=market_context_snapshot or [],
        evidence_snapshot=evidence_snapshot or {},
        ranking_snapshot=ranking_snapshot or {},
        correlation_snapshot=correlation_snapshot,
        portfolio_risk_snapshot=portfolio_risk_snapshot or {},
        market_data_timestamp=market_data_timestamp,
        code_commit=code_commit,
        configuration_versions=configuration_versions or {},
    )
    return draft.model_copy(update={"checksum": draft.compute_checksum()})
