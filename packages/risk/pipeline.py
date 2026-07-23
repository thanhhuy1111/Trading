import json
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.events.envelope import DomainEventEnvelope
from packages.governance.models import TradeIntent
from packages.outbox.repository import OutboxRepository
from packages.risk.governor import deterministic_risk_governor
from packages.risk.models import ApprovedOrder, PortfolioRiskSnapshot, RiskDecision
from packages.risk.policy import RiskPolicyConfig, default_risk_policy


class RiskPipeline:
    """Orchestrates Risk Governor evaluation, DB persistence, and Outbox event publishing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.outbox_repo = OutboxRepository(session)

    async def process_intent(
        self,
        intent: TradeIntent,
        snapshot: PortfolioRiskSnapshot,
        policy: RiskPolicyConfig = default_risk_policy,
        current_time: Optional[datetime] = None
    ) -> Tuple[RiskDecision, Optional[ApprovedOrder]]:
        eval_time = current_time or datetime.now(timezone.utc)
        decision, approved_order = deterministic_risk_governor.evaluate_intent(intent, snapshot, policy, eval_time)

        # 1. Save RiskDecision & emit Outbox event in SAME transaction
        await self._save_risk_decision(decision)
        evt_decision = DomainEventEnvelope.create(
            event_type="risk.decision_created",
            aggregate_type="risk_decision",
            aggregate_id=str(decision.decision_id),
            payload=decision.model_dump(mode="json"),
            producer="risk_governor"
        )
        await self.outbox_repo.save_event(evt_decision)

        # 2. Save ApprovedOrder & emit Outbox event if approved
        if approved_order:
            await self._save_approved_order(approved_order)
            evt_order = DomainEventEnvelope.create(
                event_type="order.approved",
                aggregate_type="approved_order",
                aggregate_id=str(approved_order.approved_order_id),
                payload=approved_order.model_dump(mode="json"),
                producer="risk_governor"
            )
            await self.outbox_repo.save_event(evt_order)

        return decision, approved_order

    async def _save_risk_decision(self, dec: RiskDecision) -> None:
        query = text("""
            INSERT INTO risk_decisions (
                id, decision_id, intent_id, account_id, result, risk_state, nav,
                base_risk_budget, adjusted_risk_budget, reference_price, conservative_entry_price,
                approved_stop_price, raw_quantity, approved_quantity, approved_notional,
                actual_risk_amount, actual_risk_pct, current_open_risk_pct, projected_open_risk_pct,
                current_total_exposure_pct, projected_total_exposure_pct, projected_symbol_allocation_pct,
                projected_correlated_exposure_pct, daily_loss_pct, weekly_loss_pct, drawdown_pct,
                checks_json, warning_codes, rejection_codes, portfolio_snapshot_id, symbol_metadata_version,
                policy_version, governor_version, decision_fingerprint, reviewed_at, valid_until,
                schema_version, created_at
            ) VALUES (
                :id, :decision_id, :intent_id, :account_id, :result, :risk_state, :nav,
                :base_risk_budget, :adjusted_risk_budget, :reference_price, :conservative_entry_price,
                :approved_stop_price, :raw_quantity, :approved_quantity, :approved_notional,
                :actual_risk_amount, :actual_risk_pct, :current_open_risk_pct, :projected_open_risk_pct,
                :current_total_exposure_pct, :projected_total_exposure_pct, :projected_symbol_allocation_pct,
                :projected_correlated_exposure_pct, :daily_loss_pct, :weekly_loss_pct, :drawdown_pct,
                :checks_json, :warning_codes, :rejection_codes, :portfolio_snapshot_id, :symbol_metadata_version,
                :policy_version, :governor_version, :decision_fingerprint, :reviewed_at, :valid_until,
                :schema_version, NOW()
            ) ON CONFLICT (decision_fingerprint) DO NOTHING
        """)
        params = {
            "id": str(dec.decision_id),
            "decision_id": str(dec.decision_id),
            "intent_id": str(dec.intent_id),
            "account_id": dec.account_id,
            "result": dec.result.value,
            "risk_state": dec.risk_state.value,
            "nav": str(dec.nav),
            "base_risk_budget": str(dec.base_risk_budget),
            "adjusted_risk_budget": str(dec.adjusted_risk_budget),
            "reference_price": str(dec.reference_price),
            "conservative_entry_price": str(dec.conservative_entry_price),
            "approved_stop_price": str(dec.approved_stop_price) if dec.approved_stop_price else None,
            "raw_quantity": str(dec.raw_quantity) if dec.raw_quantity else None,
            "approved_quantity": str(dec.approved_quantity) if dec.approved_quantity else None,
            "approved_notional": str(dec.approved_notional) if dec.approved_notional else None,
            "actual_risk_amount": str(dec.actual_risk_amount) if dec.actual_risk_amount else None,
            "actual_risk_pct": str(dec.actual_risk_pct) if dec.actual_risk_pct else None,
            "current_open_risk_pct": str(dec.current_open_risk_pct),
            "projected_open_risk_pct": str(dec.projected_open_risk_pct),
            "current_total_exposure_pct": str(dec.current_total_exposure_pct),
            "projected_total_exposure_pct": str(dec.projected_total_exposure_pct),
            "projected_symbol_allocation_pct": str(dec.projected_symbol_allocation_pct),
            "projected_correlated_exposure_pct": str(dec.projected_correlated_exposure_pct),
            "daily_loss_pct": str(dec.daily_loss_pct),
            "weekly_loss_pct": str(dec.weekly_loss_pct),
            "drawdown_pct": str(dec.drawdown_pct),
            "checks_json": json.dumps([c.model_dump(mode="json") for c in dec.checks]),
            "warning_codes": json.dumps(dec.warning_codes),
            "rejection_codes": json.dumps(dec.rejection_codes),
            "portfolio_snapshot_id": str(dec.portfolio_snapshot_id),
            "symbol_metadata_version": dec.symbol_metadata_version,
            "policy_version": dec.policy_version,
            "governor_version": dec.governor_version,
            "decision_fingerprint": dec.decision_fingerprint,
            "reviewed_at": dec.reviewed_at,
            "valid_until": dec.valid_until,
            "schema_version": dec.schema_version,
        }
        await self.session.execute(query, params)

    async def _save_approved_order(self, order: ApprovedOrder) -> None:
        query = text("""
            INSERT INTO approved_orders (
                id, approved_order_id, client_order_id, risk_decision_id, intent_id,
                exchange, symbol, side, approved_quantity, maximum_notional, approved_stop_price,
                maximum_entry_price, maximum_entry_slippage_bps, expires_at, risk_policy_version,
                governor_version, status, schema_version, created_at
            ) VALUES (
                :id, :approved_order_id, :client_order_id, :risk_decision_id, :intent_id,
                :exchange, :symbol, :side, :approved_quantity, :maximum_notional, :approved_stop_price,
                :maximum_entry_price, :maximum_entry_slippage_bps, :expires_at, :risk_policy_version,
                :governor_version, :status, :schema_version, NOW()
            ) ON CONFLICT (approved_order_id) DO NOTHING
        """)
        params = {
            "id": str(order.approved_order_id),
            "approved_order_id": str(order.approved_order_id),
            "client_order_id": str(order.client_order_id),
            "risk_decision_id": str(order.risk_decision_id),
            "intent_id": str(order.intent_id),
            "exchange": order.exchange,
            "symbol": order.symbol,
            "side": order.side,
            "approved_quantity": str(order.approved_quantity),
            "maximum_notional": str(order.maximum_notional),
            "approved_stop_price": str(order.approved_stop_price),
            "maximum_entry_price": str(order.maximum_entry_price),
            "maximum_entry_slippage_bps": str(order.maximum_entry_slippage_bps),
            "expires_at": order.expires_at,
            "risk_policy_version": order.risk_policy_version,
            "governor_version": order.governor_version,
            "status": order.status,
            "schema_version": order.schema_version,
        }
        await self.session.execute(query, params)
