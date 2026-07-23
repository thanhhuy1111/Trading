"""Pure construction of a PROPOSED TradeCandidate from a real DecisionService result.

Kept separate from packages/backtest/engine.py so the lineage-construction logic can be
unit-tested in isolation and reused outside the backtest replay loop (e.g. a future paper/live
candidate feed) without pulling in engine/replay concerns.
"""

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from packages.agents.models import SignalAction
from packages.candidates.models import CandidateStatus, TradeCandidate
from packages.governance.decision_service import DecisionResult


def _stringify_feature_values(values: dict) -> dict:
    return {k: (str(v) if v is not None else None) for k, v in values.items()}


def build_proposed_candidate(
    decision: DecisionResult,
    session_id: UUID,
    strategy_name: str,
    strategy_version: str,
    fold_number: Optional[int] = None,
) -> Optional[TradeCandidate]:
    """Returns None when the decision did not produce a TradeIntent — a candidate only exists
    once the allocator has actually proposed a trade (NO_TRADE bars are not candidates)."""
    intent = decision.trade_intent
    if intent is None:
        return None

    accepted_ids = set(decision.consensus.accepted_signals)
    critic_by_signal = {d.signal_id: d for d in decision.critic_decisions}

    supporting: List[str] = []
    opposing: List[str] = []
    dominant_agent = None
    dominant_confidence = Decimal("-1")

    for signal in decision.signals:
        critic = critic_by_signal.get(signal.signal_id)
        agrees_with_direction = signal.action == SignalAction.LONG
        if signal.signal_id in accepted_ids and agrees_with_direction:
            supporting.append(signal.agent_id)
            adj_conf = critic.adjusted_confidence if critic else signal.confidence
            if adj_conf > dominant_confidence or (
                adj_conf == dominant_confidence and (dominant_agent is None or signal.agent_id < dominant_agent)
            ):
                dominant_confidence = adj_conf
                dominant_agent = signal.agent_id
        else:
            opposing.append(signal.agent_id)

    critic_summary = ";".join(
        f"{d.agent_id}:{'APPROVED' if d.approved_for_aggregation else 'REJECTED(' + ','.join(d.rejection_codes) + ')'}"
        for d in decision.critic_decisions
    )

    risk_reward_ratio = None
    if intent.suggested_stop_price and intent.suggested_take_profit_price and intent.reference_price:
        stop_distance = intent.reference_price - intent.suggested_stop_price
        reward_distance = intent.suggested_take_profit_price - intent.reference_price
        if stop_distance > Decimal("0"):
            risk_reward_ratio = reward_distance / stop_distance

    return TradeCandidate(
        session_id=session_id,
        symbol=intent.symbol,
        timeframe=decision.feature_snapshot.timeframe.value,
        decision_timestamp=intent.generated_at,
        direction="LONG",
        agent_source=dominant_agent or "UNKNOWN",
        agent_confidence=dominant_confidence if dominant_confidence >= Decimal("0") else Decimal("0"),
        supporting_agents=supporting,
        opposing_agents=opposing,
        consensus_score=decision.consensus.weighted_confidence,
        critic_result=critic_summary,
        allocator_result=decision.allocation.result.value,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        strategy_config_hash=decision.strategy_config_hash,
        market_regime=decision.market_regime.value,
        feature_snapshot=_stringify_feature_values(decision.feature_snapshot.values),
        entry_reference=intent.reference_price,
        stop_loss=intent.suggested_stop_price,
        take_profit=intent.suggested_take_profit_price,
        risk_reward_ratio=risk_reward_ratio,
        estimated_fee_bps=intent.estimated_fee_bps,
        estimated_spread_bps=intent.estimated_spread_bps,
        estimated_slippage_bps=intent.estimated_slippage_bps,
        status=CandidateStatus.PROPOSED,
        fold_number=fold_number,
    )
