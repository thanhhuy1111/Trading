"""F-02: closed-candle ingestion worker logic (verified with a fake stream, no network)."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from packages.market_data.models import Candle, Timeframe
from packages.paper.ingestion import HandleResult, PaperIngestionWorker, WorkerState
from packages.paper.models import PaperSessionStatus
from packages.paper.pipeline import PaperPipeline
from packages.paper.session import paper_session_manager
from packages.risk.models import RiskState
from packages.risk.state_machine import risk_state_machine


def _candle(seq_price: int, close_time: datetime, *, is_closed: bool = True, ts: datetime | None = None) -> Candle:
    p = Decimal("50000") + Decimal(seq_price * 10)
    return Candle(
        exchange="binance", symbol="BTC/USDT", exchange_timestamp=ts or close_time,
        open_time=close_time - timedelta(hours=1), close_time=close_time, timeframe=Timeframe.H1,
        open_price=p, high_price=p + Decimal("50"), low_price=p - Decimal("50"),
        close_price=p + Decimal("20"), volume=Decimal("100"), trades_count=100, is_closed=is_closed,
    )


class _StubPipeline:
    def __init__(self) -> None:
        self.processed: list = []

    async def process_candle_close(self, session_id, candle) -> None:
        self.processed.append(candle)


class _FiniteSource:
    def __init__(self, items, backfills=None):
        self.items = items
        self.backfills = backfills or {}
        self.hang = False

    async def stream(self):
        for it in self.items:
            yield it
        if self.hang:
            await asyncio.Event().wait()

    async def backfill(self, symbol, timeframe, from_seq, to_seq):
        return self.backfills.get((from_seq, to_seq), [])


def _worker(pipeline=None) -> PaperIngestionWorker:
    return PaperIngestionWorker(uuid4(), pipeline or _StubPipeline())


def test_open_candle_ignored() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    w = _worker()
    res = asyncio.run(w._handle_candle(_candle(1, now, is_closed=False), 1, now=now))
    assert res == HandleResult.IGNORED_OPEN
    assert w.pipeline.processed == []


def test_closed_processed_once_and_duplicate_deduped() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    w = _worker()
    c = _candle(1, now, ts=now)
    assert asyncio.run(w._handle_candle(c, 1, now=now)) == HandleResult.PROCESSED
    assert asyncio.run(w._handle_candle(c, 1, now=now)) == HandleResult.DUPLICATE
    assert len(w.pipeline.processed) == 1


def test_out_of_order_rejected() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    w = _worker()
    asyncio.run(w._handle_candle(_candle(5, now, ts=now), 5, now=now))
    older = _candle(3, now + timedelta(hours=1), ts=now)
    assert asyncio.run(w._handle_candle(older, 3, now=now)) == HandleResult.OUT_OF_ORDER
    assert len(w.pipeline.processed) == 1


def test_sequence_gap_backfilled_returns_to_running() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    w = _worker()
    asyncio.run(w._handle_candle(_candle(1, now, ts=now), 1, now=now))
    # jump from seq 1 to seq 4 -> missing 2,3 which the source can backfill
    missing = [
        (_candle(2, now + timedelta(hours=1), ts=now), 2),
        (_candle(3, now + timedelta(hours=2), ts=now), 3),
    ]
    src = _FiniteSource([], backfills={(2, 3): missing})
    w._source = src
    res = asyncio.run(w._handle_candle(_candle(4, now + timedelta(hours=3), ts=now), 4, now=now))
    assert res == HandleResult.GAP_RECOVERED
    assert w.state == WorkerState.RUNNING
    assert len(w.pipeline.processed) == 4  # 1 + backfilled 2,3 + current 4


def test_unrecoverable_gap_requires_recovery() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    w = _worker()
    asyncio.run(w._handle_candle(_candle(1, now, ts=now), 1, now=now))
    w._source = _FiniteSource([], backfills={})  # cannot backfill
    res = asyncio.run(w._handle_candle(_candle(9, now + timedelta(hours=8), ts=now), 9, now=now))
    assert res == HandleResult.GAP_UNRECOVERABLE
    assert w.state == WorkerState.RECOVERY_REQUIRED


def test_clock_skew_degrades() -> None:
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    stale_ts = now - timedelta(seconds=30)  # 30s > 5s limit
    w = _worker()
    res = asyncio.run(w._handle_candle(_candle(1, now, ts=stale_ts), 1, now=now))
    assert res == HandleResult.SKEW_DEGRADED
    assert w.state == WorkerState.DEGRADED
    assert w.pipeline.processed == []


def test_start_processes_then_stop_cancels_cleanly() -> None:
    now = datetime.now(timezone.utc)
    items = [(_candle(1, now, ts=now), 1), (_candle(2, now + timedelta(hours=1), ts=now), 2)]
    src = _FiniteSource(items)
    src.hang = True
    w = _worker()

    async def _run():
        await w.start(src)
        await asyncio.sleep(0.05)  # let it process the two items
        processed = len(w.pipeline.processed)
        await w.stop()
        return processed

    processed = asyncio.run(_run())
    assert processed == 2
    assert w.state == WorkerState.STOPPED
    assert w._task is None


def test_degraded_session_blocks_new_entries_end_to_end() -> None:
    risk_state_machine.state = RiskState.NORMAL
    pipe = PaperPipeline()

    # Warm uptrend candles that WOULD trigger a LONG entry if RUNNING
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = Decimal("50000")
    candles = []
    for i in range(40):
        ct = t0 + timedelta(hours=i)
        step = price * Decimal("0.005")
        candles.append(Candle(
            exchange="binance", symbol="BTC/USDT", exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), trades_count=100, is_closed=True,
        ))
        price += step

    # DEGRADED session: entries must be blocked
    sess = paper_session_manager.create_session("DEGRADED_BLOCK", ["BTC/USDT"], ["1h"], initial_cash=Decimal("100000"))
    for st in [PaperSessionStatus.VALIDATING, PaperSessionStatus.WARMING_UP, PaperSessionStatus.READY,
               PaperSessionStatus.RUNNING, PaperSessionStatus.DEGRADED]:
        paper_session_manager.transition_status(sess.session_id, st)
    for c in candles:
        asyncio.run(pipe.process_candle_close(sess.session_id, c))
    pm_deg = pipe.get_position_manager(sess.session_id)
    assert all(p.status == "CLOSED" for p in pm_deg.positions.values())  # no open entry
    assert not any(p.status != "CLOSED" for p in pm_deg.positions.values())

    # RUNNING session with identical candles DOES open a position (proves the block is meaningful)
    risk_state_machine.state = RiskState.NORMAL
    sess2 = paper_session_manager.create_session("RUNNING_TRADE", ["BTC/USDT"], ["1h"], initial_cash=Decimal("100000"))
    for st in [PaperSessionStatus.VALIDATING, PaperSessionStatus.WARMING_UP, PaperSessionStatus.READY,
               PaperSessionStatus.RUNNING]:
        paper_session_manager.transition_status(sess2.session_id, st)
    for c in candles:
        asyncio.run(pipe.process_candle_close(sess2.session_id, c))
    pm_run = pipe.get_position_manager(sess2.session_id)
    assert any(p.status != "CLOSED" for p in pm_run.positions.values())
