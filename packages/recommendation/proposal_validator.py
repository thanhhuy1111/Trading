"""Opportunity gates and proposal revalidation.

`check_candidate_gates` runs BEFORE a candidate is allowed to become a proposal.
`validate_proposal` reruns the same category of checks against an already-built
proposal (used by the `validate_trade_proposal` chat tool) so a proposal shown to a
user minutes after it was generated is re-checked, not just trusted from cache.

Every threshold referenced here comes from `RecommendationConfig` -- no constants are
embedded in this module.
"""

from datetime import datetime
from typing import List, Optional, Tuple

from packages.prediction.models import ModelPrediction
from packages.recommendation.config import RecommendationConfig, recommendation_config
from packages.recommendation.models import (
    EvidenceStatus,
    StrategyEvidence,
    TradeCandidate,
    TradeProposal,
    ValidationResult,
)
from packages.recommendation.timeframes import max_allowed_staleness_seconds


def check_candidate_gates(
    candidate: TradeCandidate,
    prediction: Optional[ModelPrediction],
    evidence: StrategyEvidence,
    config: RecommendationConfig = recommendation_config,
) -> Tuple[bool, List[str]]:
    """Returns (passed, reason_codes). reason_codes is always populated with the
    codes for every gate that was evaluated as failing (empty list => all gates passed).
    """
    reasons: List[str] = []

    if candidate.freshness_seconds > max_allowed_staleness_seconds(candidate.timeframe, config):
        reasons.append("MARKET_DATA_STALE")

    if candidate.symbol not in config.symbols_list:
        reasons.append("SYMBOL_NOT_SUPPORTED")

    if candidate.timeframe not in config.timeframes_list:
        reasons.append("TIMEFRAME_NOT_SUPPORTED")

    if candidate.side != "BUY":
        reasons.append("SIDE_NOT_ALLOWED")

    if evidence.status != EvidenceStatus.APPROVED:
        reasons.append("STRATEGY_NOT_APPROVED")

    if prediction is None or not prediction.is_usable:
        reasons.append("INSUFFICIENT_EVIDENCE_PREDICTION_UNAVAILABLE")
    else:
        if prediction.probability_profit < config.min_probability_profit:
            reasons.append("PROBABILITY_BELOW_THRESHOLD")
        if prediction.calibration_score is not None and prediction.calibration_score < config.min_calibration_score:
            reasons.append("MODEL_CALIBRATION_BELOW_THRESHOLD")

    if candidate.net_edge_bps <= config.min_expected_net_return_bps:
        reasons.append("EXPECTED_NET_RETURN_NOT_POSITIVE")

    if candidate.spread_bps > config.max_spread_bps:
        reasons.append("SPREAD_TOO_WIDE")

    if candidate.liquidity_score < config.min_liquidity_score:
        reasons.append("LIQUIDITY_INSUFFICIENT")

    if candidate.market_regime == "UNKNOWN":
        reasons.append("REGIME_UNKNOWN")

    return (len(reasons) == 0, reasons)


def validate_proposal(
    proposal: TradeProposal,
    config: RecommendationConfig = recommendation_config,
    now: Optional[datetime] = None,
) -> ValidationResult:
    eval_time = now or datetime.now(proposal.expires_at.tzinfo)
    reasons: List[str] = []

    if eval_time >= proposal.expires_at:
        reasons.append("PROPOSAL_EXPIRED")

    staleness = (eval_time - proposal.data_timestamp).total_seconds()
    if staleness > max_allowed_staleness_seconds(proposal.timeframe, config):
        reasons.append("MARKET_DATA_STALE")

    if proposal.expected_net_return_bps <= config.min_expected_net_return_bps:
        reasons.append("EXPECTED_NET_RETURN_NOT_POSITIVE")

    if proposal.risk_reward_ratio < config.min_risk_reward_ratio:
        reasons.append("RISK_REWARD_BELOW_THRESHOLD")

    if proposal.probability_profit < config.min_probability_profit:
        reasons.append("PROBABILITY_BELOW_THRESHOLD")

    if proposal.market_regime == "UNKNOWN":
        reasons.append("REGIME_UNKNOWN")

    return ValidationResult(
        valid=(len(reasons) == 0),
        proposal_id=proposal.proposal_id,
        reason_codes=reasons,
        checked_at=eval_time,
    )
