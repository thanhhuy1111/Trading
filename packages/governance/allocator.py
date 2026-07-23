import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import uuid4

from packages.agents.models import AgentSignal, MarketRegime
from packages.governance.cost_estimator import cost_estimator
from packages.governance.models import (
    AllocationDecision,
    AllocationResult,
    ConsensusDirection,
    ConsensusResult,
    CriticDecision,
    IntentSide,
    TradeIntent,
)


class MetaAllocator:
    """Regime-Aware Meta Allocator calculating signal influence weights and net edge.
    
    Generates TradeIntent (status=PENDING_RISK_REVIEW, NO quantity/notional/leverage).
    """

    def evaluate_allocation(
        self,
        symbol: str,
        exchange: str,
        consensus: ConsensusResult,
        decisions: List[CriticDecision],
        signals: List[AgentSignal],
        market_regime: MarketRegime,
        current_time: datetime
    ) -> Tuple[AllocationDecision, Optional[TradeIntent]]:

        # Calculate costs & Net-Edge
        cost = cost_estimator.estimate_cost(symbol)
        conf_adj_return = consensus.weighted_expected_return_bps * consensus.weighted_confidence
        net_edge_bps = conf_adj_return - cost.total_cost_bps

        # Compute deterministic decision fingerprint
        fingerprint_src = f"{symbol}:{consensus.direction.value}:{consensus.generated_at.isoformat()}:1.0.0"
        decision_fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()

        source_signal_ids = [s.signal_id for s in signals]
        critic_decision_ids = [d.decision_id for d in decisions]
        reasons = list(consensus.reason_codes)

        # Gate 1: Check Consensus Direction
        if consensus.direction not in [ConsensusDirection.LONG, ConsensusDirection.SHORT]:
            reasons.append("NO_DIRECTIONAL_CONSENSUS")
            alloc_dec = AllocationDecision(
                allocation_id=uuid4(),
                symbol=symbol,
                result=AllocationResult.NO_TRADE,
                consensus=consensus,
                source_signal_ids=source_signal_ids,
                critic_decision_ids=critic_decision_ids,
                created_trade_intent_id=None,
                reason_codes=reasons,
                decision_fingerprint=decision_fingerprint,
                evaluated_at=current_time,
                allocator_version="1.0.0",
                policy_version="1.0.0"
            )
            return alloc_dec, None

        # Gate 2: Check Net Edge Threshold
        if net_edge_bps <= Decimal("0.0"):
            reasons.append("NET_EDGE_NOT_POSITIVE")
            alloc_dec = AllocationDecision(
                allocation_id=uuid4(),
                symbol=symbol,
                result=AllocationResult.NO_TRADE,
                consensus=consensus,
                source_signal_ids=source_signal_ids,
                critic_decision_ids=critic_decision_ids,
                created_trade_intent_id=None,
                reason_codes=reasons,
                decision_fingerprint=decision_fingerprint,
                evaluated_at=current_time,
                allocator_version="1.0.0",
                policy_version="1.0.0"
            )
            return alloc_dec, None

        # Gate 3: Check Spot MVP Short Restrictions
        if consensus.direction == ConsensusDirection.SHORT:
            reasons.append("SPOT_SHORT_NOT_EXECUTABLE")
            alloc_dec = AllocationDecision(
                allocation_id=uuid4(),
                symbol=symbol,
                result=AllocationResult.NO_TRADE,
                consensus=consensus,
                source_signal_ids=source_signal_ids,
                critic_decision_ids=critic_decision_ids,
                created_trade_intent_id=None,
                reason_codes=reasons,
                decision_fingerprint=decision_fingerprint,
                evaluated_at=current_time,
                allocator_version="1.0.0",
                policy_version="1.0.0"
            )
            return alloc_dec, None

        # All Gates Passed -> Generate TradeIntent (BUY)
        intent_id = uuid4()
        ref_price = Decimal("65000.00")
        strategy_ids = list(set(s.agent_id for s in signals))

        intent = TradeIntent(
            intent_id=intent_id,
            symbol=symbol,
            exchange=exchange,
            side=IntentSide.BUY,
            status="PENDING_RISK_REVIEW",
            strategy_ids=strategy_ids,
            source_signal_ids=source_signal_ids,
            critic_decision_ids=critic_decision_ids,
            consensus_id=consensus.consensus_id,
            market_regime=market_regime,
            expected_return_bps=consensus.weighted_expected_return_bps,
            weighted_confidence=consensus.weighted_confidence,
            estimated_fee_bps=cost.fee_bps,
            estimated_spread_bps=cost.spread_bps,
            estimated_slippage_bps=cost.slippage_bps,
            uncertainty_buffer_bps=cost.uncertainty_buffer_bps,
            net_edge_bps=net_edge_bps,
            reference_price=ref_price,
            invalidation_price=ref_price * Decimal("0.98"),
            suggested_stop_price=ref_price * Decimal("0.97"),
            suggested_take_profit_price=ref_price * Decimal("1.05"),
            horizon_minutes=60,
            maximum_entry_slippage_bps=Decimal("10.0"),
            feature_as_of_time=current_time,
            generated_at=current_time,
            expires_at=current_time + timedelta(minutes=60),
            reason_codes=reasons,
            policy_version="1.0.0",
            allocator_version="1.0.0"
        )

        reasons.append("TRADE_INTENT_SUCCESSFULLY_GENERATED")
        alloc_dec = AllocationDecision(
            allocation_id=uuid4(),
            symbol=symbol,
            result=AllocationResult.TRADE_INTENT_CREATED,
            consensus=consensus,
            source_signal_ids=source_signal_ids,
            critic_decision_ids=critic_decision_ids,
            created_trade_intent_id=intent_id,
            reason_codes=reasons,
            decision_fingerprint=decision_fingerprint,
            evaluated_at=current_time,
            allocator_version="1.0.0",
            policy_version="1.0.0"
        )

        return alloc_dec, intent


meta_allocator = MetaAllocator()
