from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.common.config import settings
from packages.execution.models import ExchangeOrderRequest, ExecutionMode, SimulatorOrderType
from packages.market_data.models import Candle
from packages.paper.adapter import PaperExchangeAdapter
from packages.paper.market_runtime import paper_market_runtime
from packages.paper.models import PaperLatencyConfig, PaperSessionStatus
from packages.paper.recovery import paper_recovery_service
from packages.paper.session import paper_session_manager
from packages.paper.warmup import warmup_service


def test_paper_session_status_transitions() -> None:
    session = paper_session_manager.create_session("SESSION_STATE_TEST", ["BTC/USDT"], ["1h"])
    assert session.status == PaperSessionStatus.CREATED

    # Valid transitions
    s2 = paper_session_manager.transition_status(session.session_id, PaperSessionStatus.VALIDATING)
    assert s2.status == PaperSessionStatus.VALIDATING

    s3 = paper_session_manager.transition_status(session.session_id, PaperSessionStatus.WARMING_UP)
    assert s3.status == PaperSessionStatus.WARMING_UP

    s4 = paper_session_manager.transition_status(session.session_id, PaperSessionStatus.READY)
    assert s4.status == PaperSessionStatus.READY

    s5 = paper_session_manager.transition_status(session.session_id, PaperSessionStatus.RUNNING)
    assert s5.status == PaperSessionStatus.RUNNING
    assert s5.started_at is not None

    # Invalid transition (RUNNING -> CREATED must raise ValueError)
    with pytest.raises(ValueError, match="INVALID_STATUS_TRANSITION"):
        paper_session_manager.transition_status(session.session_id, PaperSessionStatus.CREATED)


def test_warmup_readiness_gate() -> None:
    session = paper_session_manager.create_session("WARMUP_TEST", ["BTC/USDT"], ["1h"])

    # Insufficient candles
    report_bad = warmup_service.evaluate_readiness(session.session_id, {"BTC/USDT": 20}, min_required_candles=50)
    assert report_bad.ready is False
    assert len(report_bad.blockers) > 0

    # Sufficient candles
    report_good = warmup_service.evaluate_readiness(session.session_id, {"BTC/USDT": 100}, min_required_candles=50)
    assert report_good.ready is True
    assert len(report_good.blockers) == 0


def test_paper_exchange_adapter_execution() -> None:
    adapter = PaperExchangeAdapter(latency_config=PaperLatencyConfig(signal_processing_latency_ms=10))
    assert adapter.mode == ExecutionMode.PAPER

    now = datetime.now(timezone.utc)
    req = ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=uuid4(),
        exchange="binance",
        symbol="BTC/USDT",
        side="BUY",
        order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
        quantity=Decimal("0.5"),
        limit_price=Decimal("50000.00"),
        maximum_entry_price=Decimal("50000.00"),
        remaining_approved_quantity=Decimal("0.5"),
        remaining_maximum_notional=Decimal("25000.00"),
        submitted_at=now,
        expires_at=now + timedelta(minutes=15)
    )

    import asyncio
    resp, fills = asyncio.run(adapter.submit_order(req))

    assert resp.status == "FILLED"
    assert len(fills) == 1
    assert fills[0].quantity == Decimal("0.5")
    assert fills[0].fee > Decimal("0.0")

    # Idempotent re-submission
    resp2, fills2 = asyncio.run(adapter.submit_order(req))
    assert resp2.client_order_id == req.client_order_id
    assert len(fills2) == 1


def test_public_market_runtime_clock_skew() -> None:
    session = paper_session_manager.create_session("RUNTIME_SKEW_TEST", ["BTC/USDT"], ["1h"])
    paper_market_runtime.start_runtime(session.session_id)

    # Valid candle with fresh timestamp
    t_fresh = datetime.now(timezone.utc)
    candle_fresh = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        exchange_timestamp=t_fresh,
        open_time=t_fresh,
        close_time=t_fresh + timedelta(minutes=59),
        timeframe="1h",
        open_price=Decimal("50000.00"),
        high_price=Decimal("51000.00"),
        low_price=Decimal("49500.00"),
        close_price=Decimal("50500.00"),
        volume=Decimal("100.00"),
        trades_count=1000,
        is_closed=True
    )

    ok = paper_market_runtime.process_public_candle(session.session_id, candle_fresh, sequence_number=1)
    assert ok is True

    # Stale candle exceeding 5s clock skew threshold
    t_stale = t_fresh - timedelta(seconds=10)
    candle_stale = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        exchange_timestamp=t_stale,
        open_time=t_stale,
        close_time=t_stale + timedelta(minutes=59),
        timeframe="1h",
        open_price=Decimal("50000.00"),
        high_price=Decimal("51000.00"),
        low_price=Decimal("49500.00"),
        close_price=Decimal("50500.00"),
        volume=Decimal("100.00"),
        trades_count=1000,
        is_closed=True
    )

    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.VALIDATING)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.WARMING_UP)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.READY)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.RUNNING)

    paper_market_runtime.process_public_candle(session.session_id, candle_stale, sequence_number=2)
    assert session.status == PaperSessionStatus.DEGRADED


def test_restart_recovery_service() -> None:
    session = paper_session_manager.create_session("RECOVERY_TEST", ["BTC/USDT"], ["1h"])
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.VALIDATING)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.WARMING_UP)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.READY)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.RUNNING)
    paper_session_manager.transition_status(
        session.session_id,
        PaperSessionStatus.HALTED,
        reason="Service restart simulated"
    )

    recovered = paper_recovery_service.recover_session(session.session_id)
    assert recovered is True
    assert session.status == PaperSessionStatus.READY


def test_paper_trading_safety_invariants() -> None:
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.SYSTEM_MODE in ["SIMULATION", "MINIMAL", "PAPER_TRADING", "DEVELOPMENT", "TEST"]
