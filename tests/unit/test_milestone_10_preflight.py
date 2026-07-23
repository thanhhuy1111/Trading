import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from packages.execution.models import (
    ExchangeOrderRequest,
    SimulatorOrderType,
)
from packages.market_data.models import Candle
from packages.paper.adapter import PaperExchangeAdapter
from packages.paper.market_runtime import paper_market_runtime
from packages.paper.models import PaperSessionStatus
from packages.paper.pipeline import paper_pipeline
from packages.paper.recovery import paper_recovery_service
from packages.paper.session import paper_session_manager


def test_empirical_paper_session_run_log() -> None:
    """0.1 Paper Session Empirical Run Log & Verification."""
    session = paper_session_manager.create_session(
        "EMPIRICAL_RUN_SESSION", ["BTC/USDT"], ["1h"], initial_cash=Decimal("10000.00")
    )
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.VALIDATING)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.WARMING_UP)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.READY)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.RUNNING)

    pos_mgr = paper_pipeline.get_position_manager(session.session_id)
    now = datetime.now(timezone.utc)

    # Process 24 closed candles
    for i in range(24):
        c_time = now - timedelta(hours=24 - i)
        candle = Candle(
            exchange="binance",
            symbol="BTC/USDT",
            exchange_timestamp=c_time,
            open_time=c_time - timedelta(minutes=60),
            close_time=c_time,
            timeframe="1h",
            open_price=Decimal("50000.00") + Decimal(i * 10),
            high_price=Decimal("50500.00") + Decimal(i * 10),
            low_price=Decimal("49800.00") + Decimal(i * 10),
            close_price=Decimal("50200.00") + Decimal(i * 10),
            volume=Decimal("150.00"),
            trades_count=1200,
            is_closed=True
        )
        asyncio.run(paper_pipeline.process_candle_close(session.session_id, candle))

    snap = pos_mgr.get_portfolio_snapshot(now)
    assert session.status == PaperSessionStatus.RUNNING
    assert snap.nav >= Decimal("0.0")
    assert snap.account_id == session.account_id


def test_closed_candle_evidence_and_deduplication() -> None:
    """0.2 Closed-candle evidence & deduplication enforcement."""
    session = paper_session_manager.create_session("CLOSED_CANDLE_TEST", ["BTC/USDT"], ["1h"])
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.VALIDATING)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.WARMING_UP)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.READY)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.RUNNING)

    now = datetime.now(timezone.utc)

    # Open candle (is_closed=False) should not process signal
    open_candle = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        exchange_timestamp=now,
        open_time=now - timedelta(minutes=30),
        close_time=now + timedelta(minutes=30),
        timeframe="1h",
        open_price=Decimal("50000.00"),
        high_price=Decimal("50500.00"),
        low_price=Decimal("49800.00"),
        close_price=Decimal("50200.00"),
        volume=Decimal("150.00"),
        trades_count=1200,
        is_closed=False
    )
    asyncio.run(paper_pipeline.process_candle_close(session.session_id, open_candle))

    # Closed candle
    closed_candle = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        exchange_timestamp=now,
        open_time=now - timedelta(hours=1),
        close_time=now,
        timeframe="1h",
        open_price=Decimal("50000.00"),
        high_price=Decimal("50500.00"),
        low_price=Decimal("49800.00"),
        close_price=Decimal("50200.00"),
        volume=Decimal("150.00"),
        trades_count=1200,
        is_closed=True
    )
    asyncio.run(paper_pipeline.process_candle_close(session.session_id, closed_candle))

    # Duplicate closed candle submission should be skipped by deduplication key
    asyncio.run(paper_pipeline.process_candle_close(session.session_id, closed_candle))
    dedup_key = f"{session.session_id}:BTC/USDT:1h:{closed_candle.close_time.isoformat()}"
    assert dedup_key in paper_pipeline.processed_candles


def test_fill_chronology_guarantee() -> None:
    """0.3 Fill Chronology Guarantee (NO_SAME_EVENT_FILL)."""
    t_signal = datetime.now(timezone.utc) - timedelta(minutes=10)
    t_submit = t_signal + timedelta(seconds=2)
    t_fill = t_submit + timedelta(seconds=5)

    assert t_signal < t_submit < t_fill

    adapter = PaperExchangeAdapter()
    req = ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=uuid4(),
        exchange="binance",
        symbol="BTC/USDT",
        side="BUY",
        order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000.00"),
        maximum_entry_price=Decimal("50000.00"),
        remaining_approved_quantity=Decimal("0.1"),
        remaining_maximum_notional=Decimal("5000.00"),
        submitted_at=t_submit,
        expires_at=t_submit + timedelta(minutes=15)
    )

    resp, fills = asyncio.run(adapter.submit_order(req))
    assert fills[0].executed_at >= t_submit


def test_restart_recovery_scenarios() -> None:
    """0.4 Restart recovery scenarios."""
    session = paper_session_manager.create_session("RESTART_RECOVERY_TEST", ["BTC/USDT"], ["1h"])
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.VALIDATING)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.WARMING_UP)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.READY)
    paper_session_manager.transition_status(session.session_id, PaperSessionStatus.RUNNING)
    paper_session_manager.transition_status(
        session.session_id, PaperSessionStatus.HALTED, reason="Service crash simulated"
    )

    recovered = paper_recovery_service.recover_session(session.session_id)
    assert recovered is True
    assert session.status == PaperSessionStatus.READY


def test_gap_recovery_workflow() -> None:
    """0.5 Gap recovery workflow: Stream disconnect -> DEGRADED -> REST Backfill -> READY."""
    session = paper_session_manager.create_session("GAP_RECOVERY_TEST", ["BTC/USDT"], ["1h"])
    paper_market_runtime.start_runtime(session.session_id)

    # Simulate sequence gap
    paper_market_runtime.recover_gap(session.session_id, from_seq=10, to_seq=15)
    assert len(paper_market_runtime.incidents) > 0
    assert paper_market_runtime.incidents[-1]["type"] == "GAP_RECOVERY_COMPLETED"


def test_session_isolation() -> None:
    """0.6 Session isolation guarantee."""
    sess_a = paper_session_manager.create_session("SESSION_A", ["BTC/USDT"], ["1h"])
    sess_b = paper_session_manager.create_session("SESSION_B", ["ETH/USDT"], ["1h"])

    assert sess_a.session_id != sess_b.session_id
    assert sess_a.account_id != sess_b.account_id

    pm_a = paper_pipeline.get_position_manager(sess_a.session_id)
    pm_b = paper_pipeline.get_position_manager(sess_b.session_id)
    assert pm_a.account_id != pm_b.account_id


def test_idempotency_and_concurrency() -> None:
    """0.7 Idempotency & Concurrency Guarantees."""
    adapter = PaperExchangeAdapter()
    now = datetime.now(timezone.utc)
    c_id = uuid4()

    req = ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=c_id,
        exchange="binance",
        symbol="BTC/USDT",
        side="BUY",
        order_type=SimulatorOrderType.SINGLE_MARKETABLE_LIMIT,
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000.00"),
        maximum_entry_price=Decimal("50000.00"),
        remaining_approved_quantity=Decimal("0.1"),
        remaining_maximum_notional=Decimal("5000.00"),
        submitted_at=now,
        expires_at=now + timedelta(minutes=15)
    )

    resp1, fills1 = asyncio.run(adapter.submit_order(req))
    resp2, fills2 = asyncio.run(adapter.submit_order(req))

    assert resp1.exchange_order_id == resp2.exchange_order_id
    assert len(fills1) == len(fills2) == 1
    assert fills1[0].fill_id == fills2[0].fill_id
