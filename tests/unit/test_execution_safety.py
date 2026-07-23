from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.execution.disabled_live_adapter import disabled_live_adapter
from packages.execution.engine import execution_engine
from packages.execution.models import (
    ExchangeOrderRequest,
    ExchangeOrderStatus,
    ExecutionMode,
    SimulatorOrderType,
    TimeInForce,
)
from packages.execution.simulator_adapter import SimulatorExchangeAdapter
from packages.execution.state_machine import order_state_machine
from packages.execution.validator_gate import execution_validation_gate
from packages.risk.models import ApprovedOrder


def test_disabled_live_adapter_raises_exception_on_submit() -> None:
    now = datetime.now(timezone.utc)
    req = ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=uuid4(),
        exchange="binance",
        symbol="BTC/USDT",
        side="BUY",
        order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
        time_in_force=TimeInForce.IOC,
        quantity=Decimal("0.192"),
        limit_price=Decimal("65000.00"),
        maximum_entry_price=Decimal("65065.00"),
        remaining_approved_quantity=Decimal("0.192"),
        remaining_maximum_notional=Decimal("12492.48"),
        submitted_at=now,
        expires_at=now + timedelta(minutes=15)
    )

    with pytest.raises(RuntimeError, match="LIVE_EXECUTION_DISABLED"):
        import asyncio
        asyncio.run(disabled_live_adapter.submit_order(req))


def test_execution_validation_gate_blocks_expired_or_invalid_orders() -> None:
    now = datetime.now(timezone.utc)
    expired_order = ApprovedOrder(
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
        expires_at=now - timedelta(minutes=1), # Expired!
        status="PENDING_EXECUTION"
    )

    res = execution_validation_gate.validate_order(expired_order, now, ExecutionMode.SIMULATION)
    assert not res.valid
    assert "APPROVED_ORDER_EXPIRED" in res.rejection_codes


def test_order_state_machine_blocks_invalid_transitions() -> None:
    now = datetime.now(timezone.utc)
    client_id = uuid4()

    # Valid transition: PENDING_EXECUTION -> VALIDATING
    trans = order_state_machine.validate_transition(
        ExchangeOrderStatus.PENDING_EXECUTION,
        ExchangeOrderStatus.VALIDATING,
        client_id,
        "PRE_VALIDATION",
        [],
        now
    )
    assert trans.new_status == ExchangeOrderStatus.VALIDATING

    # Invalid transition: PENDING_EXECUTION -> FILLED (Bypassing validation)
    with pytest.raises(ValueError, match="Invalid Order State Transition"):
        order_state_machine.validate_transition(
            ExchangeOrderStatus.PENDING_EXECUTION,
            ExchangeOrderStatus.FILLED,
            client_id,
            "ILLEGAL_JUMP",
            [],
            now
        )


def test_simulator_adapter_idempotency_returns_same_order() -> None:
    async def run_test():
        adapter = SimulatorExchangeAdapter()
        now = datetime.now(timezone.utc)
        client_id = uuid4()

        req = ExchangeOrderRequest(
            approved_order_id=uuid4(),
            client_order_id=client_id,
            exchange="binance",
            symbol="BTC/USDT",
            side="BUY",
            order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
            time_in_force=TimeInForce.IOC,
            quantity=Decimal("0.192"),
            limit_price=Decimal("65000.00"),
            maximum_entry_price=Decimal("65065.00"),
            remaining_approved_quantity=Decimal("0.192"),
            remaining_maximum_notional=Decimal("12492.48"),
            submitted_at=now,
            expires_at=now + timedelta(minutes=15)
        )

        res1, fills1 = await adapter.submit_order(req)
        res2, fills2 = await adapter.submit_order(req)

        assert res1.exchange_order_id == res2.exchange_order_id
        assert res2.message == "IDEMPOTENT_SUBMISSION_MATCH"

    import asyncio
    asyncio.run(run_test())


def test_execution_engine_filled_quantity_and_price_caps() -> None:
    async def run_test():
        now = datetime.now(timezone.utc)
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
            expires_at=now + timedelta(minutes=15),
            status="PENDING_EXECUTION"
        )

        report, fills, sim_order = await execution_engine.execute_approved_order(order, now)

        assert report.final_status == ExchangeOrderStatus.FILLED
        assert report.filled_quantity <= order.approved_quantity
        assert report.average_fill_price is not None
        assert report.average_fill_price <= order.maximum_entry_price
        assert report.executed_notional <= order.maximum_notional

    import asyncio
    asyncio.run(run_test())


def test_fill_price_formula_slippage_and_bounds() -> None:
    async def run_test():
        now = datetime.now(timezone.utc)
        req = ExchangeOrderRequest(
            approved_order_id=uuid4(),
            client_order_id=uuid4(),
            exchange="binance",
            symbol="BTC/USDT",
            side="BUY",
            order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
            time_in_force=TimeInForce.IOC,
            quantity=Decimal("0.192"),
            limit_price=Decimal("65000.00"),
            maximum_entry_price=Decimal("65065.00"),
            remaining_approved_quantity=Decimal("0.192"),
            remaining_maximum_notional=Decimal("12492.48"),
            submitted_at=now,
            expires_at=now + timedelta(minutes=15)
        )

        adapter0 = SimulatorExchangeAdapter(slippage_bps=Decimal("0.0"))
        res0, fills0 = await adapter0.submit_order(req)
        assert fills0[0].price == Decimal("65000.00")

        adapter5 = SimulatorExchangeAdapter(slippage_bps=Decimal("5.0"))
        req_capped = req.model_copy(update={"client_order_id": uuid4(), "limit_price": Decimal("65065.00")})
        res5, fills5 = await adapter5.submit_order(req_capped)
        assert fills5[0].price == Decimal("65065.00")

    import asyncio
    asyncio.run(run_test())
