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
from packages.paper.pipeline import PaperPipeline
from packages.paper.recovery import paper_recovery_service
from packages.paper.reporting import PaperPortfolioReporter
from packages.paper.session import paper_session_manager
from packages.paper.warmup import warmup_service
from packages.positions.exit_protector import ExitProtector
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager
from packages.positions.models import ExitTriggerType


def _paper_request(
    *,
    now: datetime,
    client_order_id=None,
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    quantity: Decimal = Decimal("0.1"),
    price: Decimal = Decimal("50000"),
) -> ExchangeOrderRequest:
    return ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=client_order_id or uuid4(),
        exchange="binance",
        symbol=symbol,
        side=side,
        quantity=quantity,
        limit_price=price,
        maximum_entry_price=price,
        remaining_approved_quantity=quantity,
        remaining_maximum_notional=quantity * price,
        submitted_at=now,
        expires_at=now + timedelta(minutes=15),
    )


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
    assert resp2.exchange_order_id == resp.exchange_order_id
    assert fills2 == fills
    assert asyncio.run(adapter.cancel_order(req.client_order_id)) is False
    conflicting = req.model_copy(update={"quantity": Decimal("0.4")})
    with pytest.raises(ValueError, match="PAPER_IDEMPOTENCY_CONFLICT"):
        asyncio.run(adapter.submit_order(conflicting))


def test_duplicate_fill_does_not_duplicate_position_or_accounting() -> None:
    adapter = PaperExchangeAdapter()
    manager = PositionManager(
        account_id="PAPER_IDEMPOTENCY",
        ledger=PortfolioLedger(Decimal("10000"), "PAPER_IDEMPOTENCY"),
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    req = ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=uuid4(),
        exchange="binance",
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("0.1"),
        limit_price=Decimal("50000"),
        maximum_entry_price=Decimal("50000"),
        remaining_approved_quantity=Decimal("0.1"),
        remaining_maximum_notional=Decimal("5000"),
        submitted_at=now,
        expires_at=now + timedelta(minutes=15),
    )

    import asyncio
    _, fills = asyncio.run(adapter.submit_order(req))
    first_position, _ = manager.process_fill(fills[0], now)
    cash_after_first = manager.ledger.cash_balance
    second_position, duplicate_pnl = manager.process_fill(fills[0], now)

    assert second_position.quantity == first_position.quantity == Decimal("0.1")
    assert manager.ledger.cash_balance == cash_after_first
    assert len(manager.fill_history) == 1
    assert duplicate_pnl is None


def test_rejected_fill_is_retryable_and_report_is_deterministic() -> None:
    adapter = PaperExchangeAdapter()
    manager = PositionManager(
        account_id="PAPER_REPORT",
        ledger=PortfolioLedger(Decimal("1000"), "PAPER_REPORT"),
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    req = ExchangeOrderRequest(
        approved_order_id=uuid4(),
        client_order_id=uuid4(),
        exchange="binance",
        symbol="BTC/USDT",
        side="BUY",
        quantity=Decimal("1"),
        limit_price=Decimal("50000"),
        maximum_entry_price=Decimal("50000"),
        remaining_approved_quantity=Decimal("1"),
        remaining_maximum_notional=Decimal("50000"),
        submitted_at=now,
        expires_at=now + timedelta(minutes=15),
    )

    import asyncio
    _, fills = asyncio.run(adapter.submit_order(req))
    with pytest.raises(ValueError, match="INSUFFICIENT_CASH"):
        manager.process_fill(fills[0], now)
    assert fills[0].fill_id not in manager.ledger.processed_fill_ids

    manager.ledger.cash_balance = Decimal("100000")
    manager.ledger.available_cash = Decimal("100000")
    manager.equity_peak = Decimal("100000")
    manager.process_fill(fills[0], now)
    manager.update_mark_price("BTC/USDT", Decimal("49000"), now + timedelta(hours=1))

    reporter = PaperPortfolioReporter(initial_cash=Decimal("100000"))
    first = reporter.build(manager, now + timedelta(hours=1))
    second = reporter.build(manager, now + timedelta(hours=1))

    assert first == second
    assert first.trade_count == 1
    assert first.total_fees == fills[0].fee
    assert first.cash_balance >= Decimal("0")
    assert first.max_drawdown_pct > Decimal("0")
    assert first.long_only is True
    assert len(first.equity_curve) == 1


def test_sell_prevalidation_is_atomic_for_exact_symbol() -> None:
    import asyncio

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    adapter = PaperExchangeAdapter()
    manager = PositionManager(
        account_id="PAPER_ATOMIC",
        ledger=PortfolioLedger(Decimal("10000"), "PAPER_ATOMIC"),
    )
    _, buy_fills = asyncio.run(
        adapter.submit_order(_paper_request(now=now, quantity=Decimal("0.1"), price=Decimal("1000")))
    )
    manager.process_fill(buy_fills[0], now)
    cash_before = manager.ledger.cash_balance
    assets_before = dict(manager.ledger.asset_balances)
    _, sell_fills = asyncio.run(
        adapter.submit_order(
            _paper_request(
                now=now + timedelta(minutes=1),
                symbol="BTC/USDC",
                side="SELL",
                quantity=Decimal("0.1"),
                price=Decimal("1100"),
            )
        )
    )

    with pytest.raises(ValueError, match="INSUFFICIENT_POSITION_QUANTITY"):
        manager.process_fill(sell_fills[0], now + timedelta(minutes=1))

    assert manager.ledger.cash_balance == cash_before
    assert manager.ledger.asset_balances == assets_before
    assert sell_fills[0].fill_id not in manager.ledger.processed_fill_ids


def test_clean_replay_has_deterministic_accounting_ids_and_protection() -> None:
    import asyncio

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    request = _paper_request(now=now, client_order_id=uuid4(), price=Decimal("1000"))
    _, fills_a = asyncio.run(PaperExchangeAdapter().submit_order(request))
    _, fills_b = asyncio.run(PaperExchangeAdapter().submit_order(request))
    managers = [
        PositionManager("PAPER_REPLAY", PortfolioLedger(Decimal("10000"), "PAPER_REPLAY")),
        PositionManager("PAPER_REPLAY", PortfolioLedger(Decimal("10000"), "PAPER_REPLAY")),
    ]
    positions = [
        managers[0].process_fill(
            fills_a[0],
            now,
            initial_stop_price=Decimal("900"),
            take_profit_price=Decimal("1200"),
        )[0],
        managers[1].process_fill(
            fills_b[0],
            now,
            initial_stop_price=Decimal("900"),
            take_profit_price=Decimal("1200"),
        )[0],
    ]

    assert positions[0] == positions[1]
    assert managers[0].ledger.ledger_entries == managers[1].ledger.ledger_entries
    intent, _ = ExitProtector(trailing_distance_pct=Decimal("0.01")).evaluate_position_exit(
        positions[0],
        Decimal("1200"),
        now + timedelta(hours=1),
        owner_position_manager=managers[0],
    )
    assert positions[0].initial_stop_price == Decimal("900")
    assert positions[0].take_profit_price == Decimal("1200")
    assert intent is not None
    assert intent.trigger_type == ExitTriggerType.TAKE_PROFIT


def test_reports_are_point_in_time_refresh_same_timestamp_and_keep_lifetime_fees() -> None:
    import asyncio

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    adapter = PaperExchangeAdapter()
    manager = PositionManager(
        "PAPER_TEMPORAL",
        PortfolioLedger(Decimal("10000"), "PAPER_TEMPORAL"),
    )
    reporter = PaperPortfolioReporter(Decimal("10000"))
    empty = reporter.build(manager, now)
    _, buy_fills = asyncio.run(
        adapter.submit_order(_paper_request(now=now, price=Decimal("1000")))
    )
    manager.process_fill(buy_fills[0], now)
    manager.update_mark_price("BTC/USDT", Decimal("1000"), now)
    refreshed = reporter.build(manager, now)
    assert refreshed.nav != empty.nav
    assert refreshed.trade_count == 1

    sell_time = now + timedelta(hours=1)
    _, sell_fills = asyncio.run(
        adapter.submit_order(
            _paper_request(
                now=sell_time,
                side="SELL",
                quantity=Decimal("0.1"),
                price=Decimal("1100"),
            )
        )
    )
    manager.process_fill(sell_fills[0], sell_time)
    historical = reporter.build(manager, now)
    assert historical == refreshed
    assert historical.trade_count == 1
    with pytest.raises(ValueError, match="no exact point-in-time capture"):
        reporter.build(manager, now + timedelta(minutes=30))

    reopen_time = sell_time + timedelta(hours=1)
    _, reopen_fills = asyncio.run(
        adapter.submit_order(_paper_request(now=reopen_time, price=Decimal("900")))
    )
    manager.process_fill(reopen_fills[0], reopen_time)
    current = reporter.build(manager, reopen_time)
    assert current.total_fees == sum(
        (fill.fee for fill, _ in manager.fill_history),
        Decimal("0"),
    )
    assert current.trade_count == 3
    replayed_position, _ = manager.process_fill(buy_fills[0], reopen_time)
    assert replayed_position == manager.positions["BTC/USDT"]
    assert current.trade_count == len(manager.fill_history)


def test_paper_order_approval_boundaries_fail_closed() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = _paper_request(now=now).model_dump()
    base["remaining_maximum_notional"] = Decimal("1")
    with pytest.raises(ValueError, match="notional exceeds"):
        ExchangeOrderRequest(**base)

    base = _paper_request(now=now).model_dump()
    base["expires_at"] = now
    with pytest.raises(ValueError, match="expires_at"):
        ExchangeOrderRequest(**base)

    import asyncio

    sell = _paper_request(
        now=now,
        side="SELL",
        price=Decimal("1000"),
    ).model_copy(update={"reference_price": Decimal("900")})
    with pytest.raises(ValueError, match="PAPER_EXIT_PRICE_OUTSIDE_APPROVAL"):
        asyncio.run(PaperExchangeAdapter().submit_order(sell))


def test_reserved_quantity_and_temporal_updates_fail_before_mutation() -> None:
    import asyncio

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    adapter = PaperExchangeAdapter()
    manager = PositionManager(
        "PAPER_RESERVED",
        PortfolioLedger(Decimal("10000"), "PAPER_RESERVED"),
    )
    _, buy_fills = asyncio.run(
        adapter.submit_order(
            _paper_request(now=now, quantity=Decimal("1"), price=Decimal("1000"))
        )
    )
    position, _ = manager.process_fill(buy_fills[0], now)
    manager.positions[position.symbol] = position.model_copy(
        update={
            "available_quantity": Decimal("0.4"),
            "reserved_exit_quantity": Decimal("0.6"),
        }
    )
    _, sell_fills = asyncio.run(
        adapter.submit_order(
            _paper_request(
                now=now + timedelta(minutes=1),
                side="SELL",
                quantity=Decimal("0.5"),
                price=Decimal("1000"),
            )
        )
    )
    cash_before = manager.ledger.cash_balance
    with pytest.raises(ValueError, match="INSUFFICIENT_POSITION_QUANTITY"):
        manager.process_fill(sell_fills[0], now + timedelta(minutes=1))
    assert manager.ledger.cash_balance == cash_before

    manager.update_mark_price("BTC/USDT", Decimal("1100"), now + timedelta(hours=2))
    with pytest.raises(ValueError, match="OUT_OF_ORDER_MARK"):
        manager.update_mark_price("BTC/USDT", Decimal("900"), now + timedelta(hours=1))
    with pytest.raises(ValueError, match="INVALID_MARK_PRICE"):
        manager.update_mark_price("BTC/USDT", Decimal("-1"), now + timedelta(hours=3))
    assert manager.positions["BTC/USDT"].current_market_price == Decimal("1100")


def test_exit_protector_distinguishes_initial_and_trailing_stops() -> None:
    import asyncio

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    adapter = PaperExchangeAdapter()
    manager = PositionManager(
        "PAPER_EXIT_REASON",
        PortfolioLedger(Decimal("10000"), "PAPER_EXIT_REASON"),
    )
    _, fills = asyncio.run(
        adapter.submit_order(_paper_request(now=now, price=Decimal("1000")))
    )
    position, _ = manager.process_fill(
        fills[0],
        now,
        initial_stop_price=Decimal("900"),
        take_profit_price=Decimal("1200"),
    )
    protector = ExitProtector(trailing_distance_pct=Decimal("0.02"))
    initial_intent, _ = protector.evaluate_position_exit(
        position,
        Decimal("850"),
        now + timedelta(hours=1),
        owner_position_manager=manager,
    )
    assert initial_intent is not None
    assert initial_intent.trigger_type == ExitTriggerType.INITIAL_STOP

    protector = ExitProtector(trailing_distance_pct=Decimal("0.02"))
    no_intent, trailed = protector.evaluate_position_exit(
        position,
        Decimal("1100"),
        now + timedelta(hours=1),
        owner_position_manager=manager,
    )
    assert no_intent is None
    trailing_intent, _ = protector.evaluate_position_exit(
        trailed,
        Decimal("1070"),
        now + timedelta(hours=2),
        owner_position_manager=manager,
    )
    assert trailing_intent is not None
    assert trailing_intent.trigger_type == ExitTriggerType.TRAILING_STOP


def test_gap_through_stop_marks_loss_and_halts_session() -> None:
    import asyncio

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session = paper_session_manager.create_session(
        "PAPER_GAP_STOP",
        ["BTC/USDT"],
        ["1h"],
        initial_cash=Decimal("10000"),
    )
    for status in (
        PaperSessionStatus.VALIDATING,
        PaperSessionStatus.WARMING_UP,
        PaperSessionStatus.READY,
        PaperSessionStatus.RUNNING,
    ):
        paper_session_manager.transition_status(session.session_id, status)
    pipeline = PaperPipeline()
    manager = pipeline.get_position_manager(session.session_id)
    _, fills = asyncio.run(
        pipeline.adapter.submit_order(_paper_request(now=now, price=Decimal("1000")))
    )
    manager.process_fill(
        fills[0],
        now,
        initial_stop_price=Decimal("900"),
        take_profit_price=Decimal("1200"),
    )
    gap_time = now + timedelta(hours=1)
    candle = Candle(
        exchange="binance",
        symbol="BTC/USDT",
        exchange_timestamp=gap_time,
        open_time=gap_time - timedelta(hours=1),
        close_time=gap_time,
        timeframe="1h",
        open_price=Decimal("1000"),
        high_price=Decimal("1010"),
        low_price=Decimal("790"),
        close_price=Decimal("800"),
        volume=Decimal("100"),
        trades_count=100,
        is_closed=True,
    )

    asyncio.run(pipeline.process_candle_close(session.session_id, candle))

    assert session.status == PaperSessionStatus.HALTED
    assert manager.positions["BTC/USDT"].current_market_price == Decimal("800")
    assert manager.positions["BTC/USDT"].unrealized_pnl < Decimal("0")


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
