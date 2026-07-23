from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.risk.calculator import position_sizing_calculator
from packages.risk.models import (
    ApprovedOrder,
    PortfolioRiskSnapshot,
    PortfolioSnapshotSource,
    RiskState,
)
from packages.risk.policy import RiskPolicyConfig, default_risk_policy
from packages.risk.state_machine import risk_state_machine


def test_approved_order_has_no_broker_or_execution_fields():
    """Safety Test: Proves ApprovedOrder schema strictly excludes broker execution fields."""
    order = ApprovedOrder(
        risk_decision_id=uuid4(),
        intent_id=uuid4(),
        exchange="binance",
        symbol="BTC/USDT",
        side="BUY",
        approved_quantity=Decimal("0.192"),
        maximum_notional=Decimal("12492.48"),
        approved_stop_price=Decimal("63700.00"),
        maximum_entry_price=Decimal("65065.00"),
        maximum_entry_slippage_bps=Decimal("10.0"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        status="PENDING_EXECUTION"
    )

    forbidden_fields = ["exchange_order_id", "fill_quantity", "fill_price", "execution_status", "api_key"]
    for f in forbidden_fields:
        assert not hasattr(order, f), f"ApprovedOrder should NOT contain broker/execution field '{f}'"


def test_risk_policy_rejects_leverage_shorting_and_live_trading():
    """Safety Test: Proves RiskPolicyConfig strictly rejects leverage, shorting, and live trading."""
    with pytest.raises(ValueError, match="Safety Violation"):
        RiskPolicyConfig(leverage_enabled=True)

    with pytest.raises(ValueError, match="Safety Violation"):
        RiskPolicyConfig(short_selling_enabled=True)

    with pytest.raises(ValueError, match="Safety Violation"):
        RiskPolicyConfig(live_trading_enabled=True)


def test_actual_risk_never_exceeds_budget():
    """Safety Invariant: Proves actual risk amount after rounding down never exceeds allocated risk budget."""
    nav = Decimal("100000.00")
    budget = Decimal("250.00")  # 0.25% NAV
    ref_price = Decimal("65000.00")
    stop_price = Decimal("63700.00")  # Stop distance = $1,300

    sizing = position_sizing_calculator.calculate_sizing(
        nav=nav,
        adjusted_risk_budget=budget,
        reference_price=ref_price,
        stop_price=stop_price,
        available_cash=Decimal("100000.00"),
        current_symbol_exposure=Decimal("0.0"),
        current_gross_exposure=Decimal("0.0"),
        max_symbol_allocation_pct=Decimal("0.15"),
        max_total_exposure_pct=Decimal("0.50")
    )

    assert sizing.is_valid is True
    assert sizing.actual_risk_amount <= budget


def test_kill_switch_triggers_on_daily_loss_breach():
    """Kill Switch Test: Proves global RiskState transitions to HARD_STOP on daily loss breach."""
    now = datetime.now(timezone.utc)
    snapshot = PortfolioRiskSnapshot(
        account_id="ACC_1",
        nav=Decimal("100000.00"),
        cash_balance=Decimal("100000.00"),
        available_cash=Decimal("100000.00"),
        gross_exposure=Decimal("0.0"),
        net_exposure=Decimal("0.0"),
        open_risk_amount=Decimal("0.0"),
        realized_pnl_today=Decimal("-2000.00"),  # 2.0% daily loss (exceeds 1.5% limit)
        realized_pnl_week=Decimal("-2000.00"),
        equity_peak=Decimal("100000.00"),
        current_drawdown_pct=Decimal("0.02"),
        data_as_of=now,
        source=PortfolioSnapshotSource.STATIC_TEST
    )

    state, reasons, kill_triggered = risk_state_machine.evaluate_state(snapshot, default_risk_policy, now)
    assert state == RiskState.HARD_STOP
    assert kill_triggered is True
    assert "DAILY_LOSS_HARD_LIMIT_BREACHED (2.00%)" in reasons
