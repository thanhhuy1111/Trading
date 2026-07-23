"""Builds a TradeProposal from a real TradeCandidate + calibrated ModelPrediction.

This is the only place a TradeProposal is constructed. It never invents entry, stop,
take-profit, probability, or return figures -- every numeric field traces back to either
the DecisionService output (candidate) or the Prediction Service (prediction). If the
prediction is not usable (no calibrated model), `build()` returns None and the caller
must surface INSUFFICIENT_EVIDENCE rather than call this function with placeholder data.
"""

from datetime import datetime, timedelta
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Optional

from packages.prediction.models import ModelPrediction
from packages.recommendation.config import RecommendationConfig, recommendation_config
from packages.recommendation.cost_service import recommendation_cost_service
from packages.recommendation.models import (
    DecisionLineage,
    ProposalStatus,
    StrategyEvidence,
    TradeCandidate,
    TradeProposal,
)
from packages.recommendation.opportunity_ranker import opportunity_ranker


def _risk_reward_ratio(entry: Decimal, stop: Decimal, take_profit: Decimal) -> Optional[Decimal]:
    try:
        risk = entry - stop
        reward = take_profit - entry
        if risk <= Decimal("0"):
            return None
        return (reward / risk).quantize(Decimal("0.0001"))
    except (DivisionByZero, InvalidOperation):
        return None


class ProposalBuilder:
    def build(
        self,
        candidate: TradeCandidate,
        prediction: ModelPrediction,
        evidence: StrategyEvidence,
        config: RecommendationConfig = recommendation_config,
        now: Optional[datetime] = None,
    ) -> Optional[TradeProposal]:
        if not prediction.is_usable:
            return None

        eval_time = now or datetime.now(candidate.data_timestamp.tzinfo)

        entry_from = candidate.reference_price
        entry_to = candidate.reference_price * (Decimal("1") + config.entry_chase_bps / Decimal("10000"))
        stop_loss = candidate.stop_loss
        take_profit = candidate.take_profit

        rr = _risk_reward_ratio(entry_from, stop_loss, take_profit)
        if rr is None:
            return None

        cost = recommendation_cost_service.estimate(candidate.symbol)
        expected_gross_return_bps = candidate.expected_return_bps
        expected_net_return_bps = (expected_gross_return_bps - cost.total_cost_bps).quantize(Decimal("0.01"))
        expected_downside_bps = ((entry_from - stop_loss) / entry_from * Decimal("10000")).quantize(Decimal("0.01"))

        score = opportunity_ranker.score(
            candidate=candidate,
            probability_profit=prediction.probability_profit,
            expected_net_return_bps=expected_net_return_bps,
            expected_downside_bps=expected_downside_bps,
            evidence_status=evidence.status.value,
            config=config,
        )

        lineage = DecisionLineage(
            feature_snapshot_id=candidate.feature_snapshot_id,
            market_regime=candidate.market_regime,
            signal_ids=candidate.decision_lineage.signal_ids,
            critic_decision_ids=candidate.decision_lineage.critic_decision_ids,
            consensus_id=candidate.decision_lineage.consensus_id,
            allocation_id=candidate.decision_lineage.allocation_id,
            trade_intent_id=candidate.decision_lineage.trade_intent_id,
            prediction_id=prediction.prediction_id,
            evidence_id=evidence.evidence_id,
            config_hash=candidate.config_hash,
        )

        explanation_facts = [
            f"Market regime classified as {candidate.market_regime} on {candidate.timeframe}.",
            f"Strategies in agreement: {', '.join(candidate.strategy_names)}.",
            (
                "Expected gross return is a target-distance x confidence proxy from the strategy agents, "
                "not a calibrated statistical forecast."
            ),
            f"Estimated round-trip cost: {cost.total_cost_bps} bps (fee+spread+slippage+uncertainty buffer).",
            f"Probability of profit is the calibrated model estimate (model_version={prediction.model_version}).",
        ]
        invalidation_conditions = [
            f"Price closes below stop-loss {stop_loss}.",
            f"Feature snapshot becomes stale (> {config.max_market_data_staleness_seconds}s old).",
            "Market regime reclassifies away from the regime this proposal was generated under.",
        ]
        risk_flags = list(candidate.reason_codes)
        if evidence.status.value != "APPROVED":
            risk_flags.append(f"STRATEGY_EVIDENCE_STATUS_{evidence.status.value}")

        return TradeProposal(
            symbol=candidate.symbol,
            side=candidate.side,
            status=ProposalStatus.PROPOSED,
            timeframe=candidate.timeframe,
            horizon_minutes=candidate.horizon_minutes,
            entry_from=entry_from,
            entry_to=entry_to,
            stop_loss=stop_loss,
            take_profit_levels=[take_profit],
            probability_profit=prediction.probability_profit,
            expected_gross_return_bps=expected_gross_return_bps,
            estimated_cost_bps=cost.total_cost_bps,
            expected_net_return_bps=expected_net_return_bps,
            expected_downside_bps=expected_downside_bps,
            risk_reward_ratio=rr,
            opportunity_score=score,
            market_regime=candidate.market_regime,
            data_timestamp=candidate.data_timestamp,
            freshness_seconds=candidate.freshness_seconds,
            generated_at=eval_time,
            expires_at=eval_time + timedelta(minutes=config.default_proposal_ttl_minutes),
            strategy_name="+".join(candidate.strategy_names),
            strategy_version=candidate.strategy_version,
            model_version=prediction.model_version,
            feature_version=candidate.feature_set_version,
            config_hash=candidate.config_hash,
            evidence_id=evidence.evidence_id,
            explanation_facts=explanation_facts,
            invalidation_conditions=invalidation_conditions,
            risk_flags=risk_flags,
            decision_lineage=lineage,
        )


proposal_builder = ProposalBuilder()
