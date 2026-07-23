"""Deterministic opportunity scoring and ranking.

Score = (calibrated_probability x positive_expected_net_return x regime_reliability x
         liquidity_score x evidence_reliability) / expected_downside

All factors are normalized to [0, 1] (except the downside denominator, which is floored to
avoid division blow-up). Given the same candidate, prediction, evidence, and config, the
score -- and therefore the rank -- is always identical. The Gemini chat agent never sees
this module and cannot influence the score or the ranking order.
"""

from decimal import Decimal
from typing import List, Optional

from packages.recommendation.config import RecommendationConfig, recommendation_config
from packages.recommendation.models import TradeCandidate, TradeProposal

_REGIME_RELIABILITY = {
    "TREND_UP": Decimal("0.90"),
    "TREND_DOWN": Decimal("0.90"),
    "SIDEWAYS": Decimal("0.70"),
    "LOW_VOLATILITY": Decimal("0.60"),
    "HIGH_VOLATILITY": Decimal("0.30"),
    "TRANSITION": Decimal("0.40"),
    "LIQUIDITY_RISK": Decimal("0.10"),
    "UNKNOWN": Decimal("0.0"),
}

_EVIDENCE_RELIABILITY = {
    "APPROVED": Decimal("1.0"),
    "RESEARCH_ONLY": Decimal("0.50"),
    "STALE": Decimal("0.30"),
    "INSUFFICIENT": Decimal("0.0"),
    "REJECTED": Decimal("0.0"),
}


def regime_reliability(market_regime: str) -> Decimal:
    return _REGIME_RELIABILITY.get(market_regime, Decimal("0.0"))


def evidence_reliability(evidence_status: str) -> Decimal:
    return _EVIDENCE_RELIABILITY.get(evidence_status, Decimal("0.0"))


class OpportunityRanker:
    def score(
        self,
        *,
        candidate: TradeCandidate,
        probability_profit: Decimal,
        expected_net_return_bps: Decimal,
        expected_downside_bps: Decimal,
        evidence_status: str,
        config: RecommendationConfig = recommendation_config,
    ) -> Decimal:
        prob = max(Decimal("0.0"), min(probability_profit, Decimal("1.0")))
        norm_return = max(
            Decimal("0.0"),
            min(expected_net_return_bps / config.ranker_return_normalization_bps, Decimal("1.0")),
        )
        regime = regime_reliability(candidate.market_regime)
        liquidity = max(Decimal("0.0"), min(candidate.liquidity_score, Decimal("1.0")))
        evidence = evidence_reliability(evidence_status)

        weighted_prob = prob * config.ranker_probability_weight
        weighted_return = norm_return * config.ranker_return_weight
        weighted_regime = regime * config.ranker_regime_weight
        weighted_liquidity = liquidity * config.ranker_liquidity_weight
        weighted_evidence = evidence * config.ranker_evidence_weight

        composite = weighted_prob * weighted_return * weighted_regime * weighted_liquidity * weighted_evidence

        downside_norm = max(
            Decimal("0.0"),
            min(expected_downside_bps / config.ranker_return_normalization_bps, Decimal("1.0")),
        )
        denominator = max(downside_norm, config.ranker_downside_floor)

        return (composite / denominator).quantize(Decimal("0.000001"))

    def rank(self, proposals: List[TradeProposal], max_results: Optional[int] = None) -> List[TradeProposal]:
        ordered = sorted(proposals, key=lambda p: p.opportunity_score, reverse=True)
        if max_results is not None:
            return ordered[:max_results]
        return ordered


opportunity_ranker = OpportunityRanker()
