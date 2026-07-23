import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import uuid4

from packages.governance.models import TradeIntent
from packages.risk.calculator import position_sizing_calculator
from packages.risk.models import (
    ApprovedOrder,
    PortfolioRiskSnapshot,
    RiskCheckResult,
    RiskCheckSeverity,
    RiskDecision,
    RiskDecisionResult,
    RiskState,
)
from packages.risk.policy import RiskPolicyConfig, default_risk_policy
from packages.risk.state_machine import risk_state_machine


class DeterministicRiskGovernor:
    """Independent, Deterministic Risk Governor with absolute veto authority."""

    def evaluate_intent(
        self,
        intent: TradeIntent,
        snapshot: PortfolioRiskSnapshot,
        policy: RiskPolicyConfig = default_risk_policy,
        current_time: Optional[datetime] = None
    ) -> Tuple[RiskDecision, Optional[ApprovedOrder]]:
        eval_time = current_time or datetime.now(timezone.utc)

        checks: List[RiskCheckResult] = []
        warning_codes: List[str] = []
        rejection_codes: List[str] = []

        # 1. Intent Freshness & Validity Check
        if intent.expires_at <= current_time:
            rejection_codes.append("INTENT_EXPIRED")
            checks.append(RiskCheckResult(
                check_name="IntentFreshnessCheck",
                passed=False,
                severity=RiskCheckSeverity.CRITICAL,
                reason_codes=["INTENT_EXPIRED"],
                explanation=["TradeIntent expiration time has passed."]
            ))

        if intent.status != "PENDING_RISK_REVIEW":
            rejection_codes.append("INVALID_INTENT_STATUS")
            checks.append(RiskCheckResult(
                check_name="IntentStatusCheck",
                passed=False,
                severity=RiskCheckSeverity.CRITICAL,
                reason_codes=["INVALID_INTENT_STATUS"],
                explanation=[f"TradeIntent status must be PENDING_RISK_REVIEW, got {intent.status}."]
            ))

        # 2. Portfolio Snapshot Freshness Check
        snapshot_age = (eval_time - snapshot.data_as_of).total_seconds()
        if snapshot_age > policy.max_portfolio_snapshot_age_seconds:
            rejection_codes.append("PORTFOLIO_SNAPSHOT_STALE")
            checks.append(RiskCheckResult(
                check_name="SnapshotFreshnessCheck",
                passed=False,
                severity=RiskCheckSeverity.CRITICAL,
                reason_codes=["PORTFOLIO_SNAPSHOT_STALE"],
                explanation=[
                    f"Snapshot age ({snapshot_age:.0f}s) exceeds max threshold "
                    f"({policy.max_portfolio_snapshot_age_seconds}s)."
                ]
            ))

        # 3. Global Risk State Check
        state, state_reasons, kill_triggered = risk_state_machine.evaluate_state(snapshot, policy, eval_time)
        if kill_triggered or state == RiskState.HARD_STOP:
            rejection_codes.append("HARD_STOP_ACTIVE")
            rejection_codes.extend(state_reasons)
            checks.append(RiskCheckResult(
                check_name="GlobalRiskStateCheck",
                passed=False,
                severity=RiskCheckSeverity.CRITICAL,
                reason_codes=state_reasons,
                explanation=["Kill Switch / Hard Stop is active."]
            ))

        if state == RiskState.SOFT_STOP:
            rejection_codes.append("SOFT_STOP_ACTIVE")
            checks.append(RiskCheckResult(
                check_name="GlobalRiskStateCheck",
                passed=False,
                severity=RiskCheckSeverity.HIGH,
                reason_codes=["SOFT_STOP_ACTIVE"],
                explanation=["Soft Stop active. No new position entries allowed."]
            ))

        # Stop price determination & check
        stop_price = intent.suggested_stop_price or intent.invalidation_price
        if not stop_price or stop_price >= intent.reference_price:
            rejection_codes.append("INVALID_APPROVED_STOP_PRICE")
            checks.append(RiskCheckResult(
                check_name="StopPriceCheck",
                passed=False,
                severity=RiskCheckSeverity.CRITICAL,
                reason_codes=["INVALID_APPROVED_STOP_PRICE"],
                explanation=["Approved stop price must be strictly lower than reference entry price."]
            ))

        # Stop distance check
        if stop_price and stop_price < intent.reference_price:
            stop_dist_pct = (intent.reference_price - stop_price) / intent.reference_price
            if stop_dist_pct < policy.min_stop_distance_pct or stop_dist_pct > policy.max_stop_distance_pct:
                rejection_codes.append("STOP_DISTANCE_OUT_OF_BOUNDS")
                checks.append(RiskCheckResult(
                    check_name="StopDistanceCheck",
                    passed=False,
                    severity=RiskCheckSeverity.HIGH,
                    reason_codes=["STOP_DISTANCE_OUT_OF_BOUNDS"],
                    explanation=[
                        f"Stop distance {stop_dist_pct * 100:.2f}% is outside bounds "
                        f"[{policy.min_stop_distance_pct * 100:.2f}%, {policy.max_stop_distance_pct * 100:.2f}%]."
                    ]
                ))

        # Early Rejection Return
        if len(rejection_codes) > 0:
            result_code = RiskDecisionResult.HARD_STOPPED if (state == RiskState.HARD_STOP) else (
                RiskDecisionResult.SOFT_STOPPED if (state == RiskState.SOFT_STOP) else RiskDecisionResult.REJECTED
            )

            fingerprint_src = f"{intent.intent_id}:{snapshot.snapshot_id}:{policy.version}:1.0.0"
            decision_fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()

            daily_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_today / snapshot.nav)
            weekly_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_week / snapshot.nav)

            decision = RiskDecision(
                intent_id=intent.intent_id,
                account_id=snapshot.account_id,
                result=result_code,
                risk_state=state,
                nav=snapshot.nav,
                base_risk_budget=Decimal("0.0"),
                adjusted_risk_budget=Decimal("0.0"),
                reference_price=intent.reference_price,
                conservative_entry_price=intent.reference_price,
                approved_stop_price=stop_price,
                current_open_risk_pct=snapshot.open_risk_amount / snapshot.nav,
                projected_open_risk_pct=snapshot.open_risk_amount / snapshot.nav,
                current_total_exposure_pct=snapshot.gross_exposure / snapshot.nav,
                projected_total_exposure_pct=snapshot.gross_exposure / snapshot.nav,
                projected_symbol_allocation_pct=Decimal("0.0"),
                projected_correlated_exposure_pct=Decimal("0.0"),
                daily_loss_pct=daily_loss_pct,
                weekly_loss_pct=weekly_loss_pct,
                drawdown_pct=snapshot.current_drawdown_pct,
                checks=checks,
                warning_codes=warning_codes,
                rejection_codes=rejection_codes,
                portfolio_snapshot_id=snapshot.snapshot_id,
                decision_fingerprint=decision_fingerprint,
                reviewed_at=current_time,
                valid_until=intent.expires_at
            )
            return decision, None

        # 4. Sizing Calculation
        base_budget = snapshot.nav * policy.risk_per_trade_pct
        state_mult = Decimal("0.75") if state == RiskState.WARNING else Decimal("1.0")
        adjusted_budget = base_budget * state_mult * intent.weighted_confidence

        current_symbol_exp = sum(p.market_value for p in snapshot.positions if p.symbol == intent.symbol)

        sizing = position_sizing_calculator.calculate_sizing(
            nav=snapshot.nav,
            adjusted_risk_budget=adjusted_budget,
            reference_price=intent.reference_price,
            stop_price=stop_price,
            available_cash=snapshot.available_cash,
            current_symbol_exposure=current_symbol_exp,
            current_gross_exposure=snapshot.gross_exposure,
            max_symbol_allocation_pct=policy.max_symbol_allocation_pct,
            max_total_exposure_pct=policy.max_total_exposure_pct,
            reserve_cash_pct=policy.reserve_cash_pct
        )

        if not sizing.is_valid:
            rejection_codes.append(sizing.rejection_reason or "SIZING_CALCULATION_FAILED")
            checks.append(RiskCheckResult(
                check_name="PositionSizingCheck",
                passed=False,
                severity=RiskCheckSeverity.HIGH,
                reason_codes=[sizing.rejection_reason or "SIZING_CALCULATION_FAILED"],
                explanation=["Position sizing calculation returned invalid result."]
            ))

            fingerprint_src = f"{intent.intent_id}:{snapshot.snapshot_id}:{policy.version}:1.0.0"
            decision_fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()
            daily_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_today / snapshot.nav)
            weekly_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_week / snapshot.nav)

            decision = RiskDecision(
                intent_id=intent.intent_id,
                account_id=snapshot.account_id,
                result=RiskDecisionResult.REJECTED,
                risk_state=state,
                nav=snapshot.nav,
                base_risk_budget=base_budget,
                adjusted_risk_budget=adjusted_budget,
                reference_price=intent.reference_price,
                conservative_entry_price=sizing.conservative_entry_price,
                approved_stop_price=stop_price,
                current_open_risk_pct=snapshot.open_risk_amount / snapshot.nav,
                projected_open_risk_pct=snapshot.open_risk_amount / snapshot.nav,
                current_total_exposure_pct=snapshot.gross_exposure / snapshot.nav,
                projected_total_exposure_pct=snapshot.gross_exposure / snapshot.nav,
                projected_symbol_allocation_pct=current_symbol_exp / snapshot.nav,
                projected_correlated_exposure_pct=Decimal("0.0"),
                daily_loss_pct=daily_loss_pct,
                weekly_loss_pct=weekly_loss_pct,
                drawdown_pct=snapshot.current_drawdown_pct,
                checks=checks,
                warning_codes=warning_codes,
                rejection_codes=rejection_codes,
                portfolio_snapshot_id=snapshot.snapshot_id,
                decision_fingerprint=decision_fingerprint,
                reviewed_at=current_time,
                valid_until=intent.expires_at
            )
            return decision, None

        # 5. Successful Approval Decision & ApprovedOrder Generation
        proj_open_risk = (snapshot.open_risk_amount + sizing.actual_risk_amount) / snapshot.nav
        proj_total_exp = (snapshot.gross_exposure + sizing.approved_notional) / snapshot.nav
        proj_symbol_alloc = (current_symbol_exp + sizing.approved_notional) / snapshot.nav

        fingerprint_src = f"{intent.intent_id}:{snapshot.snapshot_id}:{policy.version}:{sizing.approved_quantity}:1.0.0"
        decision_fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()

        daily_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_today / snapshot.nav)
        weekly_loss_pct = max(Decimal("0.0"), -snapshot.realized_pnl_week / snapshot.nav)

        decision_id = uuid4()
        decision = RiskDecision(
            decision_id=decision_id,
            intent_id=intent.intent_id,
            account_id=snapshot.account_id,
            result=RiskDecisionResult.APPROVED,
            risk_state=state,
            nav=snapshot.nav,
            base_risk_budget=base_budget,
            adjusted_risk_budget=adjusted_budget,
            reference_price=intent.reference_price,
            conservative_entry_price=sizing.conservative_entry_price,
            approved_stop_price=stop_price,
            raw_quantity=sizing.raw_quantity,
            approved_quantity=sizing.approved_quantity,
            approved_notional=sizing.approved_notional,
            actual_risk_amount=sizing.actual_risk_amount,
            actual_risk_pct=sizing.actual_risk_pct,
            current_open_risk_pct=snapshot.open_risk_amount / snapshot.nav,
            projected_open_risk_pct=proj_open_risk,
            current_total_exposure_pct=snapshot.gross_exposure / snapshot.nav,
            projected_total_exposure_pct=proj_total_exp,
            projected_symbol_allocation_pct=proj_symbol_alloc,
            projected_correlated_exposure_pct=Decimal("0.0"),
            daily_loss_pct=daily_loss_pct,
            weekly_loss_pct=weekly_loss_pct,
            drawdown_pct=snapshot.current_drawdown_pct,
            checks=checks,
            warning_codes=warning_codes,
            rejection_codes=[],
            portfolio_snapshot_id=snapshot.snapshot_id,
            decision_fingerprint=decision_fingerprint,
            reviewed_at=current_time,
            valid_until=current_time + timedelta(minutes=15)
        )

        approved_order = ApprovedOrder(
            approved_order_id=uuid4(),
            client_order_id=uuid4(),
            risk_decision_id=decision_id,
            intent_id=intent.intent_id,
            exchange=intent.exchange,
            symbol=intent.symbol,
            side="BUY",
            approved_quantity=sizing.approved_quantity,
            maximum_notional=sizing.approved_notional,
            approved_stop_price=stop_price,
            maximum_entry_price=sizing.conservative_entry_price,
            maximum_entry_slippage_bps=intent.maximum_entry_slippage_bps,
            expires_at=current_time + timedelta(minutes=15),
            risk_policy_version=policy.version,
            governor_version="1.0.0",
            status="PENDING_EXECUTION"
        )

        return decision, approved_order


deterministic_risk_governor = DeterministicRiskGovernor()
