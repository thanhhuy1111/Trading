import json
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.agents.models import AgentSignal, MarketRegime
from packages.common.logger import logger
from packages.events.envelope import DomainEventEnvelope
from packages.governance.allocator import meta_allocator
from packages.governance.consensus import signal_consensus_engine
from packages.governance.critic import critic_agent
from packages.governance.models import (
    AllocationDecision,
    ConsensusResult,
    CriticDecision,
    TradeIntent,
)
from packages.governance.validator_gate import signal_validation_gate
from packages.outbox.repository import OutboxRepository


class GovernancePipeline:
    """Orchestrates Signal Validation -> Critic Scrutiny -> Consensus -> Meta Allocator -> Outbox Publishing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.outbox_repo = OutboxRepository(session)

    async def process_signals(
        self,
        symbol: str,
        exchange: str,
        signals: List[AgentSignal],
        market_regime: MarketRegime,
        current_time: datetime
    ) -> Tuple[List[CriticDecision], ConsensusResult, AllocationDecision, Optional[TradeIntent]]:

        # 1. Validation & Critic Scrutiny
        decisions_and_signals: List[Tuple[CriticDecision, AgentSignal]] = []
        critic_decisions: List[CriticDecision] = []

        for sig in signals:
            val_res = signal_validation_gate.validate_signal(sig, current_time)
            if not val_res.valid:
                logger.warning(
                    "Signal validation failed",
                    extra={"signal_id": str(sig.signal_id), "rejections": val_res.rejection_codes}
                )

            dec = critic_agent.review_signal(sig, current_time)
            critic_decisions.append(dec)
            decisions_and_signals.append((dec, sig))

            # Save CriticDecision & publish Outbox event in SAME transaction
            await self._save_critic_decision(dec)
            evt = DomainEventEnvelope.create(
                event_type="critic.decision_created",
                aggregate_type="critic_decision",
                aggregate_id=str(dec.decision_id),
                payload=dec.model_dump(mode="json"),
                producer="critic_agent"
            )
            await self.outbox_repo.save_event(evt)

        # 2. Consensus Engine Evaluation
        consensus = signal_consensus_engine.evaluate_consensus(symbol, decisions_and_signals, current_time)
        await self._save_consensus_result(consensus)

        evt_consensus = DomainEventEnvelope.create(
            event_type="consensus.result_created",
            aggregate_type="consensus_result",
            aggregate_id=str(consensus.consensus_id),
            payload=consensus.model_dump(mode="json"),
            producer="consensus_engine"
        )
        await self.outbox_repo.save_event(evt_consensus)

        # 3. Meta Allocator Evaluation
        alloc_dec, intent = meta_allocator.evaluate_allocation(
            symbol=symbol,
            exchange=exchange,
            consensus=consensus,
            decisions=critic_decisions,
            signals=signals,
            market_regime=market_regime,
            current_time=current_time
        )

        await self._save_allocation_decision(alloc_dec)
        evt_alloc = DomainEventEnvelope.create(
            event_type="allocation.decision_created",
            aggregate_type="allocation_decision",
            aggregate_id=str(alloc_dec.allocation_id),
            payload=alloc_dec.model_dump(mode="json"),
            producer="meta_allocator"
        )
        await self.outbox_repo.save_event(evt_alloc)

        # 4. Save TradeIntent & Outbox Event if generated
        if intent:
            await self._save_trade_intent(intent)
            evt_intent = DomainEventEnvelope.create(
                event_type="trade.intent_created",
                aggregate_type="trade_intent",
                aggregate_id=str(intent.intent_id),
                payload=intent.model_dump(mode="json"),
                producer="meta_allocator"
            )
            await self.outbox_repo.save_event(evt_intent)

        return critic_decisions, consensus, alloc_dec, intent

    async def _save_critic_decision(self, dec: CriticDecision) -> None:
        query = text("""
            INSERT INTO critic_decisions (
                id, decision_id, signal_id, agent_id, approved_for_aggregation,
                original_confidence, adjusted_confidence, confidence_penalty, estimated_cost_bps,
                risk_flags, warning_codes, rejection_codes, review_components, reviewed_at,
                valid_until, critic_version, policy_version, schema_version, created_at
            ) VALUES (
                :id, :decision_id, :signal_id, :agent_id, :approved_for_aggregation,
                :original_confidence, :adjusted_confidence, :confidence_penalty, :estimated_cost_bps,
                :risk_flags, :warning_codes, :rejection_codes, :review_components, :reviewed_at,
                :valid_until, :critic_version, :policy_version, :schema_version, NOW()
            ) ON CONFLICT (signal_id, critic_version, policy_version) DO NOTHING
        """)
        params = {
            "id": str(dec.decision_id),
            "decision_id": str(dec.decision_id),
            "signal_id": str(dec.signal_id),
            "agent_id": dec.agent_id,
            "approved_for_aggregation": dec.approved_for_aggregation,
            "original_confidence": str(dec.original_confidence),
            "adjusted_confidence": str(dec.adjusted_confidence),
            "confidence_penalty": str(dec.confidence_penalty),
            "estimated_cost_bps": str(dec.estimated_cost_bps),
            "risk_flags": json.dumps(dec.risk_flags),
            "warning_codes": json.dumps(dec.warning_codes),
            "rejection_codes": json.dumps(dec.rejection_codes),
            "review_components": json.dumps([c.model_dump(mode="json") for c in dec.review_components]),
            "reviewed_at": dec.reviewed_at,
            "valid_until": dec.valid_until,
            "critic_version": dec.critic_version,
            "policy_version": dec.policy_version,
            "schema_version": dec.schema_version,
        }
        await self.session.execute(query, params)

    async def _save_consensus_result(self, res: ConsensusResult) -> None:
        query = text("""
            INSERT INTO consensus_results (
                id, consensus_id, symbol, direction, agreement_score, disagreement_score,
                participating_signals, accepted_signals, rejected_signals, weighted_confidence,
                weighted_expected_return_bps, reason_codes, generated_at, consensus_version
            ) VALUES (
                :id, :consensus_id, :symbol, :direction, :agreement_score, :disagreement_score,
                :participating_signals, :accepted_signals, :rejected_signals, :weighted_confidence,
                :weighted_expected_return_bps, :reason_codes, :generated_at, :consensus_version
            ) ON CONFLICT (consensus_id) DO NOTHING
        """)
        params = {
            "id": str(res.consensus_id),
            "consensus_id": str(res.consensus_id),
            "symbol": res.symbol,
            "direction": res.direction.value,
            "agreement_score": str(res.agreement_score),
            "disagreement_score": str(res.disagreement_score),
            "participating_signals": json.dumps([str(s) for s in res.participating_signals]),
            "accepted_signals": json.dumps([str(s) for s in res.accepted_signals]),
            "rejected_signals": json.dumps([str(s) for s in res.rejected_signals]),
            "weighted_confidence": str(res.weighted_confidence),
            "weighted_expected_return_bps": str(res.weighted_expected_return_bps),
            "reason_codes": json.dumps(res.reason_codes),
            "generated_at": res.generated_at,
            "consensus_version": res.consensus_version,
        }
        await self.session.execute(query, params)

    async def _save_allocation_decision(self, alloc: AllocationDecision) -> None:
        query = text("""
            INSERT INTO allocation_decisions (
                id, allocation_id, symbol, result, consensus_id, source_signal_ids,
                critic_decision_ids, created_trade_intent_id, reason_codes, decision_fingerprint,
                evaluated_at, allocator_version, policy_version, created_at
            ) VALUES (
                :id, :allocation_id, :symbol, :result, :consensus_id, :source_signal_ids,
                :critic_decision_ids, :created_trade_intent_id, :reason_codes, :decision_fingerprint,
                :evaluated_at, :allocator_version, :policy_version, NOW()
            ) ON CONFLICT (decision_fingerprint) DO NOTHING
        """)
        params = {
            "id": str(alloc.allocation_id),
            "allocation_id": str(alloc.allocation_id),
            "symbol": alloc.symbol,
            "result": alloc.result.value,
            "consensus_id": str(alloc.consensus.consensus_id),
            "source_signal_ids": json.dumps([str(s) for s in alloc.source_signal_ids]),
            "critic_decision_ids": json.dumps([str(d) for d in alloc.critic_decision_ids]),
            "created_trade_intent_id": str(alloc.created_trade_intent_id) if alloc.created_trade_intent_id else None,
            "reason_codes": json.dumps(alloc.reason_codes),
            "decision_fingerprint": alloc.decision_fingerprint,
            "evaluated_at": alloc.evaluated_at,
            "allocator_version": alloc.allocator_version,
            "policy_version": alloc.policy_version,
        }
        await self.session.execute(query, params)

    async def _save_trade_intent(self, intent: TradeIntent) -> None:
        query = text("""
            INSERT INTO trade_intents (
                id, intent_id, symbol, exchange, side, status, strategy_ids, source_signal_ids,
                critic_decision_ids, consensus_id, market_regime, expected_return_bps, weighted_confidence,
                estimated_fee_bps, estimated_spread_bps, estimated_slippage_bps, uncertainty_buffer_bps,
                net_edge_bps, reference_price, invalidation_price, suggested_stop_price, suggested_take_profit_price,
                horizon_minutes, maximum_entry_slippage_bps, feature_as_of_time, generated_at, expires_at,
                reason_codes, policy_version, allocator_version, schema_version, created_at
            ) VALUES (
                :id, :intent_id, :symbol, :exchange, :side, :status, :strategy_ids, :source_signal_ids,
                :critic_decision_ids, :consensus_id, :market_regime, :expected_return_bps, :weighted_confidence,
                :estimated_fee_bps, :estimated_spread_bps, :estimated_slippage_bps, :uncertainty_buffer_bps,
                :net_edge_bps, :reference_price, :invalidation_price, :suggested_stop_price,
                :suggested_take_profit_price, :horizon_minutes, :maximum_entry_slippage_bps,
                :feature_as_of_time, :generated_at, :expires_at, :reason_codes, :policy_version,
                :allocator_version, :schema_version, NOW()
            ) ON CONFLICT (intent_id) DO NOTHING
        """)
        params = {
            "id": str(intent.intent_id),
            "intent_id": str(intent.intent_id),
            "symbol": intent.symbol,
            "exchange": intent.exchange,
            "side": intent.side.value,
            "status": intent.status,
            "strategy_ids": json.dumps(intent.strategy_ids),
            "source_signal_ids": json.dumps([str(s) for s in intent.source_signal_ids]),
            "critic_decision_ids": json.dumps([str(d) for d in intent.critic_decision_ids]),
            "consensus_id": str(intent.consensus_id),
            "market_regime": intent.market_regime.value,
            "expected_return_bps": str(intent.expected_return_bps),
            "weighted_confidence": str(intent.weighted_confidence),
            "estimated_fee_bps": str(intent.estimated_fee_bps),
            "estimated_spread_bps": str(intent.estimated_spread_bps),
            "estimated_slippage_bps": str(intent.estimated_slippage_bps),
            "uncertainty_buffer_bps": str(intent.uncertainty_buffer_bps),
            "net_edge_bps": str(intent.net_edge_bps),
            "reference_price": str(intent.reference_price),
            "invalidation_price": str(intent.invalidation_price) if intent.invalidation_price else None,
            "suggested_stop_price": str(intent.suggested_stop_price) if intent.suggested_stop_price else None,
            "suggested_take_profit_price": (
                str(intent.suggested_take_profit_price) if intent.suggested_take_profit_price else None
            ),
            "horizon_minutes": intent.horizon_minutes,
            "maximum_entry_slippage_bps": str(intent.maximum_entry_slippage_bps),
            "feature_as_of_time": intent.feature_as_of_time,
            "generated_at": intent.generated_at,
            "expires_at": intent.expires_at,
            "reason_codes": json.dumps(intent.reason_codes),
            "policy_version": intent.policy_version,
            "allocator_version": intent.allocator_version,
            "schema_version": intent.schema_version,
        }
        await self.session.execute(query, params)
