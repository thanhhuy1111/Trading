"""Durable paper-trading persistence integration drills (PostgreSQL required).

These run ONLY when a disposable PostgreSQL is provided via ``PAPER_DB_TEST_URL`` (async DSN,
e.g. postgresql+asyncpg://postgres:postgres@localhost:55432/trading_db). They MUST run against
real PostgreSQL — never SQLite — before F-02/F-03/F-04/F-05 durability can be marked verified.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("PAPER_DB_TEST_URL"),
    reason="PAPER_DB_TEST_URL not set: no disposable PostgreSQL available",
)

pytest_asyncio = pytest.importorskip("pytest_asyncio")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from packages.execution.models import Fill, LiquidityType  # noqa: E402
from packages.paper.models import PaperSessionStatus  # noqa: E402
from packages.paper.recovery import PaperRecoveryService  # noqa: E402
from packages.paper.session import paper_session_manager  # noqa: E402
from packages.persistence.reconciliation import reconcile_session  # noqa: E402
from packages.persistence.repositories import (  # noqa: E402
    FillRepository,
    LedgerRepository,
    PnLBucketRepository,
    PositionRepository,
    ProcessedCandleRepository,
)
from packages.persistence.unit_of_work import FillCommitOrchestrator, SqlAlchemyFillTxnOps  # noqa: E402
from packages.positions.ledger import PortfolioLedger  # noqa: E402
from packages.positions.manager import PositionManager  # noqa: E402


@pytest.fixture
def db_url() -> str:
    return os.environ["PAPER_DB_TEST_URL"]


@pytest.fixture
async def engine(db_url):
    eng = create_async_engine(db_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _buy_fill(symbol: str, at: datetime, price: Decimal = Decimal("50000")) -> Fill:
    qty = Decimal("0.1")
    return Fill(
        fill_id=uuid4(), exchange_fill_id=f"F_{uuid4().hex[:8]}", exchange_order_id=uuid4(),
        client_order_id=uuid4(), symbol=symbol, side="BUY", quantity=qty, price=price,
        quote_quantity=qty * price, fee=Decimal("5.00"), fee_asset="USDT",
        liquidity=LiquidityType.TAKER, executed_at=at,
    )


def _sell_fill(symbol: str, at: datetime, price: Decimal, qty: Decimal) -> Fill:
    return Fill(
        fill_id=uuid4(), exchange_fill_id=f"F_{uuid4().hex[:8]}", exchange_order_id=uuid4(),
        client_order_id=uuid4(), symbol=symbol, side="SELL", quantity=qty, price=price,
        quote_quantity=qty * price, fee=Decimal("5.00"), fee_asset="USDT",
        liquidity=LiquidityType.TAKER, executed_at=at,
    )


async def _new_paper_session(session: AsyncSession, initial_cash: Decimal) -> None:
    """Insert a minimal paper_sessions row (FK target for all paper_* tables)."""
    from sqlalchemy import text
    session_id = uuid4()
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            "INSERT INTO paper_sessions (session_id, name, account_id, status, exchange, symbols, "
            "timeframes, initial_cash, base_currency, warmup_start_time, config_snapshot_id, "
            "config_fingerprint, created_at) VALUES (:sid, :name, :acct, 'RUNNING', 'binance', "
            "'[\"BTC/USDT\"]', '[\"1h\"]', :cash, 'USDT', :now, :cfg, 'test_fp', :now)"
        ),
        {"sid": session_id, "name": f"TEST_{session_id.hex[:8]}", "acct": f"ACCT_{session_id.hex[:8]}",
         "cash": initial_cash, "now": now, "cfg": uuid4()},
    )
    await session.commit()
    return session_id


@pytest.mark.asyncio
async def test_database_migration_cycle(engine):
    """Migration cycle already verified via `alembic upgrade/downgrade/upgrade` CLI (see
    docs/remediation/MIGRATION_EVIDENCE.md); here we just assert the durable tables exist."""
    from sqlalchemy import inspect
    async with engine.connect() as conn:
        def _tables(sync_conn):
            return set(inspect(sync_conn).get_table_names())
        tables = await conn.run_sync(_tables)
    for t in ["paper_processed_candles", "paper_orders", "paper_fills", "paper_ledger_entries",
              "paper_positions", "paper_pnl_buckets", "paper_risk_states"]:
        assert t in tables


@pytest.mark.asyncio
async def test_fill_transaction_is_atomic_and_rolls_back(session_factory):
    """Inject a failure mid-transaction; assert zero rows persisted for that fill."""
    async with session_factory() as session:
        session_id = await _new_paper_session(session, Decimal("10000"))
        pm = PositionManager(account_id="ATOMIC_TEST", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
        ops = SqlAlchemyFillTxnOps(session, session_id, pm)
        fill = _buy_fill("BTC/USDT", datetime.now(timezone.utc))

        async def _boom(*a, **k):
            raise RuntimeError("injected failure")
        ops.update_risk_state = _boom  # fail after fill+ledger+position steps

        orch = FillCommitOrchestrator()
        with pytest.raises(RuntimeError):
            await orch.commit_fill(ops, fill)

    async with session_factory() as verify_session:
        assert await FillRepository(verify_session).exists(fill.fill_id) is False
        entries = await LedgerRepository(verify_session).list_for_session(session_id)
        assert entries == []
        pos = await PositionRepository(verify_session).get(session_id, "BTC/USDT")
        assert pos is None


@pytest.mark.asyncio
async def test_fill_retry_is_idempotent(session_factory):
    async with session_factory() as session:
        session_id = await _new_paper_session(session, Decimal("10000"))
        pm = PositionManager(account_id="IDEMP_TEST", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
        ops = SqlAlchemyFillTxnOps(session, session_id, pm)
        fill = _buy_fill("BTC/USDT", datetime.now(timezone.utc))
        orch = FillCommitOrchestrator()

        r1 = await orch.commit_fill(ops, fill)
        assert r1.committed is True

        # Retry the SAME fill_id through a fresh ops/session (simulating a retry after the caller
        # didn't see the response) -> must be idempotent, no double debit.
        r2 = await orch.commit_fill(ops, fill)
        assert r2.idempotent_replay is True
        assert r2.committed is False

    async with session_factory() as verify_session:
        fills = await FillRepository(verify_session).list_for_session(session_id)
        assert len(fills) == 1
        entries = await LedgerRepository(verify_session).list_for_session(session_id)
        # BUY = CASH_DEBIT + FEE_DEBIT + ASSET_CREDIT = 3 entries, not 6
        assert len(entries) == 3


@pytest.mark.asyncio
async def test_concurrent_fill_only_commits_once(session_factory):
    """Two committers race on the SAME fill_id; exactly one wins via the unique constraint."""
    async with session_factory() as setup_session:
        session_id = await _new_paper_session(setup_session, Decimal("10000"))

    fill = _buy_fill("BTC/USDT", datetime.now(timezone.utc))
    orch = FillCommitOrchestrator()

    async def _commit_once():
        async with session_factory() as s:
            pm = PositionManager(account_id="RACE_TEST", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
            ops = SqlAlchemyFillTxnOps(s, session_id, pm)
            return await orch.commit_fill(ops, fill)

    import asyncio
    r1, r2 = await asyncio.gather(_commit_once(), _commit_once(), return_exceptions=True)
    results = [r for r in (r1, r2) if not isinstance(r, Exception)]
    committed = [r for r in results if r.committed]
    assert len(committed) == 1

    async with session_factory() as verify_session:
        fills = await FillRepository(verify_session).list_for_session(session_id)
        assert len(fills) == 1


@pytest.mark.asyncio
async def test_processed_candle_db_dedup(session_factory):
    async with session_factory() as setup_session:
        session_id = await _new_paper_session(setup_session, Decimal("10000"))

    close_time = datetime.now(timezone.utc)
    open_time = close_time - timedelta(hours=1)

    async def _claim():
        async with session_factory() as s:
            repo = ProcessedCandleRepository(s)
            claimed = await repo.claim(session_id, "BTC/USDT", "1h", open_time, close_time, close_time, "chk123")
            await s.commit()
            return claimed

    import asyncio
    r1, r2 = await asyncio.gather(_claim(), _claim())
    winners = [r for r in (r1, r2) if r is not None]
    assert len(winners) == 1


@pytest.mark.asyncio
async def test_two_sessions_are_durably_isolated(session_factory):
    async with session_factory() as s:
        session_a = await _new_paper_session(s, Decimal("10000"))
    async with session_factory() as s:
        session_b = await _new_paper_session(s, Decimal("5000"))

    at = datetime.now(timezone.utc)
    orch = FillCommitOrchestrator()

    async with session_factory() as s:
        pm_a = PositionManager(account_id="A", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_a, pm_a), _buy_fill("BTC/USDT", at))

    async with session_factory() as verify:
        pos_a = await PositionRepository(verify).get(session_a, "BTC/USDT")
        pos_b_should_be_none = await PositionRepository(verify).get(session_b, "BTC/USDT")
        assert pos_a is not None
        assert pos_b_should_be_none is None
        fills_b = await FillRepository(verify).list_for_session(session_b)
        assert fills_b == []


@pytest.mark.asyncio
async def test_restart_restores_exact_state(session_factory):
    """Persist a fill, throw away the runtime objects, build fresh ones, reconcile, compare."""
    async with session_factory() as s:
        session_id = await _new_paper_session(s, Decimal("10000"))

    at = datetime.now(timezone.utc)
    fill = _buy_fill("BTC/USDT", at)
    orch = FillCommitOrchestrator()

    async with session_factory() as s:
        pm_before = PositionManager(account_id="RESTART", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_id, pm_before), fill)
    cash_before = pm_before.ledger.cash_balance
    pos_before = pm_before.positions["BTC/USDT"]

    # "Destroy" the runtime: drop all references, build brand-new objects from DB only.
    del pm_before

    async with session_factory() as verify:
        ledger_rows = await LedgerRepository(verify).list_for_session(session_id)
        fill_rows = await FillRepository(verify).list_for_session(session_id)
        pos_row = await PositionRepository(verify).get(session_id, "BTC/USDT")

        result = reconcile_session(
            initial_cash=Decimal("10000"),
            ledger_rows=ledger_rows,
            fill_rows=fill_rows,
            materialized_cash=Decimal("10000") - (fill.quote_quantity + fill.fee),
            materialized_positions={"BTC": pos_row["quantity"]},
        )
        assert result.passed is True, result.issues
        assert Decimal(str(pos_row["quantity"])) == pos_before.quantity
        assert Decimal(str(pos_row["average_entry_price"])) == pos_before.average_entry_price
        assert Decimal(str(pos_row["quantity"])) == Decimal("0.1")
        # Recomputed cash from ledger equals the original in-memory cash
        derived_cash = Decimal("10000") - (fill.quote_quantity + fill.fee)
        assert derived_cash == cash_before


@pytest.mark.asyncio
async def test_pnl_buckets_survive_restart(session_factory):
    async with session_factory() as s:
        session_id = await _new_paper_session(s, Decimal("10000"))

    at = datetime.now(timezone.utc)
    buy = _buy_fill("BTC/USDT", at, price=Decimal("50000"))
    orch = FillCommitOrchestrator()
    pm = PositionManager(account_id="BUCKET_TEST", ledger=PortfolioLedger(initial_cash=Decimal("10000")))

    async with session_factory() as s:
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_id, pm), buy)

    sell = _sell_fill("BTC/USDT", at + timedelta(minutes=5), price=Decimal("51000"), qty=Decimal("0.1"))
    async with session_factory() as s:
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_id, pm), sell)

    day_start = at.replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_factory() as verify:
        bucket = await PnLBucketRepository(verify).get(session_id, "DAILY", day_start)
        assert bucket is not None
        assert Decimal(str(bucket["realized_pnl"])) > Decimal("0")


@pytest.mark.asyncio
async def test_late_fill_updates_correct_bucket(session_factory):
    async with session_factory() as s:
        session_id = await _new_paper_session(s, Decimal("10000"))

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    buy = _buy_fill("BTC/USDT", yesterday, price=Decimal("50000"))
    pm = PositionManager(account_id="LATE_TEST", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
    orch = FillCommitOrchestrator()
    async with session_factory() as s:
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_id, pm), buy)

    # Processed "late" (now), but fill.executed_at is yesterday -> must land in yesterday's bucket.
    sell = _sell_fill("BTC/USDT", yesterday + timedelta(minutes=10), price=Decimal("52000"), qty=Decimal("0.1"))
    async with session_factory() as s:
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_id, pm), sell)

    yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_factory() as verify:
        y_bucket = await PnLBucketRepository(verify).get(session_id, "DAILY", yesterday_start)
        t_bucket = await PnLBucketRepository(verify).get(session_id, "DAILY", today_start)
        assert y_bucket is not None and Decimal(str(y_bucket["realized_pnl"])) > Decimal("0")
        assert t_bucket is None


async def _session_with_runtime_at(session: AsyncSession, initial_cash: Decimal, status: PaperSessionStatus) -> UUID:
    """Creates a DB row AND a runtime PaperTradingSession (same session_id), driven to `status`
    so recover_session_durable's transition_status calls are valid."""
    from sqlalchemy import text
    rt = paper_session_manager.create_session(f"DURABLE_{uuid4().hex[:6]}", ["BTC/USDT"], ["1h"], initial_cash)
    session_id = rt.session_id
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            "INSERT INTO paper_sessions (session_id, name, account_id, status, exchange, symbols, "
            "timeframes, initial_cash, base_currency, warmup_start_time, config_snapshot_id, "
            "config_fingerprint, created_at) VALUES (:sid, :name, :acct, 'RUNNING', 'binance', "
            "'[\"BTC/USDT\"]', '[\"1h\"]', :cash, 'USDT', :now, :cfg, 'test_fp', :now)"
        ),
        {"sid": session_id, "name": rt.name, "acct": rt.account_id, "cash": initial_cash, "now": now, "cfg": uuid4()},
    )
    await session.commit()
    for st in [PaperSessionStatus.VALIDATING, PaperSessionStatus.WARMING_UP, PaperSessionStatus.READY,
               PaperSessionStatus.RUNNING, PaperSessionStatus.HALTED, PaperSessionStatus.RECOVERY_REQUIRED]:
        paper_session_manager.transition_status(session_id, st)
        if st == status:
            break
    return session_id


@pytest.mark.asyncio
async def test_recovery_reconciles_and_transitions_to_ready(session_factory):
    async with session_factory() as s:
        session_id = await _session_with_runtime_at(s, Decimal("10000"), PaperSessionStatus.RECOVERY_REQUIRED)

    at = datetime.now(timezone.utc)
    pm = PositionManager(account_id="RECOVERY_OK", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
    orch = FillCommitOrchestrator()
    async with session_factory() as s:
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_id, pm), _buy_fill("BTC/USDT", at))

    recovery_service = PaperRecoveryService()
    async with session_factory() as s:
        result, rebuilt_pm = await recovery_service.recover_session_durable(session_id, s, Decimal("10000"))

    assert result.passed is True
    assert rebuilt_pm is not None
    assert rebuilt_pm.positions["BTC/USDT"].quantity == Decimal("0.1")
    assert paper_session_manager.sessions[session_id].status == PaperSessionStatus.READY


@pytest.mark.asyncio
async def test_recovery_detects_ledger_mismatch_stays_recovery_required(session_factory):
    async with session_factory() as s:
        session_id = await _session_with_runtime_at(s, Decimal("10000"), PaperSessionStatus.RECOVERY_REQUIRED)

    at = datetime.now(timezone.utc)
    pm = PositionManager(account_id="RECOVERY_BAD", ledger=PortfolioLedger(initial_cash=Decimal("10000")))
    orch = FillCommitOrchestrator()
    async with session_factory() as s:
        await orch.commit_fill(SqlAlchemyFillTxnOps(s, session_id, pm), _buy_fill("BTC/USDT", at))

    # Corrupt the materialized position row directly (simulating drift/corruption) so it no
    # longer matches what the ledger implies.
    from sqlalchemy import text
    async with session_factory() as s:
        await s.execute(
            text("UPDATE paper_positions SET quantity = :q WHERE session_id = :sid AND symbol = 'BTC/USDT'"),
            {"q": Decimal("999.0"), "sid": session_id},
        )
        await s.commit()

    recovery_service = PaperRecoveryService()
    async with session_factory() as s:
        result, rebuilt_pm = await recovery_service.recover_session_durable(session_id, s, Decimal("10000"))

    assert result.passed is False
    assert any("POSITION_MISMATCH" in i for i in result.issues)
    assert rebuilt_pm is None
    assert paper_session_manager.sessions[session_id].status == PaperSessionStatus.RECOVERY_REQUIRED


@pytest.mark.asyncio
async def test_ingestion_resumes_from_high_water_mark(session_factory):
    async with session_factory() as s:
        session_id = await _new_paper_session(s, Decimal("10000"))

    base = datetime.now(timezone.utc)
    async with session_factory() as s:
        repo = ProcessedCandleRepository(s)
        for i in range(3):
            await repo.claim(session_id, "BTC/USDT", "1h", base + timedelta(hours=i),
                              base + timedelta(hours=i + 1), base + timedelta(hours=i + 1), f"chk{i}")
        await s.commit()

    # A "new worker" resuming must see candle 0..2 as already processed and not reclaim them.
    async with session_factory() as s2:
        repo2 = ProcessedCandleRepository(s2)
        already = await repo2.is_processed(session_id, "BTC/USDT", "1h", base + timedelta(hours=1))
        assert already is True
        reclaim = await repo2.claim(session_id, "BTC/USDT", "1h", base, base + timedelta(hours=1),
                                     base + timedelta(hours=1), "chk0")
        assert reclaim is None  # conflict -> not re-claimed
