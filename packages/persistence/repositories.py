"""Session-scoped SQLAlchemy repositories for durable paper-trading state (F-02/F-03/F-04/F-05).

Each repository takes an ``AsyncSession`` and does NOT commit internally — the caller (the
``FillCommitOrchestrator`` / recovery service) owns the transaction boundary, per the round 4
requirement that persistence orchestration lives at the application/service layer.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.persistence.schema import (
    paper_fills,
    paper_ledger_entries,
    paper_orders,
    paper_pnl_buckets,
    paper_positions,
    paper_processed_candles,
    paper_risk_states,
)


class ProcessedCandleRepository:
    """DB-backed candle-processing claim (F-02). The unique constraint on
    (session_id, symbol, timeframe, close_time) is the actual race-safety mechanism — the
    ``claim`` INSERT either succeeds (this worker owns the candle) or violates the constraint
    (someone else already claimed it), never an ``if exists`` check."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self,
        session_id: UUID,
        symbol: str,
        timeframe: str,
        open_time: datetime,
        close_time: datetime,
        event_time: datetime,
        payload_checksum: str,
        source: str = "public_stream",
    ) -> Optional[UUID]:
        """Attempts to claim this candle. Returns the new row id on success, None on conflict."""
        stmt = (
            pg_insert(paper_processed_candles)
            .values(
                id=uuid4(),
                session_id=session_id,
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                event_time=event_time,
                source=source,
                payload_checksum=payload_checksum,
                processing_status="PROCESSING",
                claimed_at=datetime.now(close_time.tzinfo),
            )
            .on_conflict_do_nothing(constraint="uq_paper_candle_key")
            .returning(paper_processed_candles.c.id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        return row[0] if row else None

    async def mark_completed(self, candle_id: UUID, decision_id: Optional[UUID]) -> None:
        await self.session.execute(
            paper_processed_candles.update()
            .where(paper_processed_candles.c.id == candle_id)
            .values(processing_status="COMPLETED", decision_id=decision_id, completed_at=datetime.utcnow())
        )

    async def is_processed(self, session_id: UUID, symbol: str, timeframe: str, close_time: datetime) -> bool:
        stmt = select(paper_processed_candles.c.id).where(
            paper_processed_candles.c.session_id == session_id,
            paper_processed_candles.c.symbol == symbol,
            paper_processed_candles.c.timeframe == timeframe,
            paper_processed_candles.c.close_time == close_time,
        )
        result = await self.session.execute(stmt)
        return result.first() is not None


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_client_order_id(self, session_id: UUID, client_order_id: UUID) -> Optional[Dict[str, Any]]:
        stmt = select(paper_orders).where(
            paper_orders.c.session_id == session_id,
            paper_orders.c.client_order_id == client_order_id,
        )
        result = await self.session.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else None

    async def insert(
        self,
        session_id: UUID,
        client_order_id: UUID,
        approved_order_id: UUID,
        symbol: str,
        side: str,
        quantity: Decimal,
        limit_price: Decimal,
        maximum_entry_price: Decimal,
    ) -> UUID:
        order_id = uuid4()
        stmt = (
            pg_insert(paper_orders)
            .values(
                id=order_id,
                session_id=session_id,
                client_order_id=client_order_id,
                approved_order_id=approved_order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                limit_price=limit_price,
                maximum_entry_price=maximum_entry_price,
                status="PENDING_EXECUTION",
            )
            .on_conflict_do_nothing(constraint="uq_paper_order_client_id")
            .returning(paper_orders.c.id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        return row[0] if row else order_id

    async def mark_filled(self, session_id: UUID, client_order_id: UUID, filled_quantity: Decimal) -> None:
        await self.session.execute(
            paper_orders.update()
            .where(paper_orders.c.session_id == session_id, paper_orders.c.client_order_id == client_order_id)
            .values(status="FILLED", filled_quantity=filled_quantity)
        )

    async def list_for_session(self, session_id: UUID) -> List[Dict[str, Any]]:
        result = await self.session.execute(select(paper_orders).where(paper_orders.c.session_id == session_id))
        return [dict(r) for r in result.mappings().all()]


class FillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, fill_id: UUID) -> bool:
        stmt = select(paper_fills.c.fill_id).where(paper_fills.c.fill_id == fill_id)
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def insert(self, fill: Any, session_id: UUID) -> None:
        """Raises sqlalchemy.exc.IntegrityError if fill_id already exists (primary key)."""
        await self.session.execute(
            paper_fills.insert().values(
                fill_id=fill.fill_id,
                session_id=session_id,
                client_order_id=fill.client_order_id,
                symbol=fill.symbol,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.price,
                quote_quantity=fill.quote_quantity,
                fee=fill.fee,
                fee_asset=fill.fee_asset,
                event_time=fill.executed_at,
            )
        )

    async def list_for_session(self, session_id: UUID) -> List[Dict[str, Any]]:
        result = await self.session.execute(select(paper_fills).where(paper_fills.c.session_id == session_id))
        return [dict(r) for r in result.mappings().all()]


class LedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_entries(self, session_id: UUID, fill_id: UUID, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            return
        await self.session.execute(
            paper_ledger_entries.insert(),
            [
                {
                    "entry_id": e["entry_id"],
                    "session_id": session_id,
                    "fill_id": fill_id,
                    "asset": e["asset"],
                    "entry_type": e["entry_type"],
                    "amount": e["amount"],
                    "currency": e.get("currency", "USDT"),
                    "event_time": e["event_time"],
                }
                for e in entries
            ],
        )

    async def list_for_session(self, session_id: UUID) -> List[Dict[str, Any]]:
        result = await self.session.execute(
            select(paper_ledger_entries).where(paper_ledger_entries.c.session_id == session_id)
        )
        return [dict(r) for r in result.mappings().all()]


class PositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, session_id: UUID, symbol: str) -> Optional[Dict[str, Any]]:
        stmt = select(paper_positions).where(
            paper_positions.c.session_id == session_id, paper_positions.c.symbol == symbol
        )
        result = await self.session.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else None

    async def upsert(
        self,
        session_id: UUID,
        symbol: str,
        quantity: Decimal,
        average_entry_price: Decimal,
        total_cost_basis: Decimal,
        realized_pnl_delta: Decimal,
        status: str,
        position_id: Optional[UUID] = None,
        total_fees: Decimal = Decimal("0"),
        initial_stop_price: Optional[Decimal] = None,
        active_stop_price: Optional[Decimal] = None,
        take_profit_price: Optional[Decimal] = None,
        trailing_stop_price: Optional[Decimal] = None,
        current_market_price: Optional[Decimal] = None,
        market_value: Optional[Decimal] = None,
        opened_at: Optional[datetime] = None,
        last_fill_at: Optional[datetime] = None,
    ) -> None:
        stable_position_id = position_id or uuid5(
            NAMESPACE_URL,
            f"paper-position:{session_id}:{symbol}",
        )
        stmt = (
            pg_insert(paper_positions)
            .values(
                id=stable_position_id,
                session_id=session_id,
                symbol=symbol,
                quantity=quantity,
                average_entry_price=average_entry_price,
                total_cost_basis=total_cost_basis,
                realized_pnl=realized_pnl_delta,
                total_fees=total_fees,
                initial_stop_price=initial_stop_price,
                active_stop_price=active_stop_price,
                take_profit_price=take_profit_price,
                trailing_stop_price=trailing_stop_price,
                current_market_price=current_market_price,
                market_value=market_value,
                opened_at=opened_at,
                last_fill_at=last_fill_at,
                status=status,
                version=1,
            )
            .on_conflict_do_update(
                constraint="uq_paper_position_session_symbol",
                set_={
                    "id": stable_position_id,
                    "quantity": quantity,
                    "average_entry_price": average_entry_price,
                    "total_cost_basis": total_cost_basis,
                    "realized_pnl": paper_positions.c.realized_pnl + realized_pnl_delta,
                    "total_fees": total_fees,
                    "initial_stop_price": initial_stop_price,
                    "active_stop_price": active_stop_price,
                    "take_profit_price": take_profit_price,
                    "trailing_stop_price": trailing_stop_price,
                    "current_market_price": current_market_price,
                    "market_value": market_value,
                    "opened_at": opened_at,
                    "last_fill_at": last_fill_at,
                    "status": status,
                    "version": paper_positions.c.version + 1,
                    "updated_at": datetime.utcnow(),
                },
            )
        )
        await self.session.execute(stmt)

    async def list_for_session(self, session_id: UUID) -> List[Dict[str, Any]]:
        result = await self.session.execute(select(paper_positions).where(paper_positions.c.session_id == session_id))
        return [dict(r) for r in result.mappings().all()]


class PnLBucketRepository:
    """Atomic upsert (INSERT ... ON CONFLICT DO UPDATE realized_pnl = realized_pnl + delta)
    so concurrent fills into the same bucket never lose an update (F-05)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_realized_pnl(
        self,
        session_id: UUID,
        bucket_type: str,
        bucket_start: datetime,
        bucket_end: datetime,
        pnl_delta: Decimal,
        fee_delta: Decimal,
    ) -> None:
        stmt = (
            pg_insert(paper_pnl_buckets)
            .values(
                id=uuid4(),
                session_id=session_id,
                bucket_type=bucket_type,
                bucket_start=bucket_start,
                bucket_end=bucket_end,
                realized_pnl=pnl_delta,
                fees=fee_delta,
                version=1,
            )
            .on_conflict_do_update(
                constraint="uq_paper_pnl_bucket",
                set_={
                    "realized_pnl": paper_pnl_buckets.c.realized_pnl + pnl_delta,
                    "fees": paper_pnl_buckets.c.fees + fee_delta,
                    "version": paper_pnl_buckets.c.version + 1,
                    "updated_at": datetime.utcnow(),
                },
            )
        )
        await self.session.execute(stmt)

    async def get(self, session_id: UUID, bucket_type: str, bucket_start: datetime) -> Optional[Dict[str, Any]]:
        stmt = select(paper_pnl_buckets).where(
            paper_pnl_buckets.c.session_id == session_id,
            paper_pnl_buckets.c.bucket_type == bucket_type,
            paper_pnl_buckets.c.bucket_start == bucket_start,
        )
        result = await self.session.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else None

    async def list_for_session(self, session_id: UUID) -> List[Dict[str, Any]]:
        result = await self.session.execute(
            select(paper_pnl_buckets).where(paper_pnl_buckets.c.session_id == session_id)
        )
        return [dict(r) for r in result.mappings().all()]


class RiskStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, session_id: UUID, state: str, equity_peak: Decimal, drawdown_pct: Decimal) -> None:
        stmt = (
            pg_insert(paper_risk_states)
            .values(session_id=session_id, state=state, equity_peak=equity_peak,
                     current_drawdown_pct=drawdown_pct, version=1)
            .on_conflict_do_update(
                index_elements=[paper_risk_states.c.session_id],
                set_={
                    "state": state,
                    "equity_peak": equity_peak,
                    "current_drawdown_pct": drawdown_pct,
                    "version": paper_risk_states.c.version + 1,
                    "updated_at": datetime.utcnow(),
                },
            )
        )
        await self.session.execute(stmt)

    async def get(self, session_id: UUID) -> Optional[Dict[str, Any]]:
        stmt = select(paper_risk_states).where(paper_risk_states.c.session_id == session_id)
        result = await self.session.execute(stmt)
        row = result.mappings().first()
        return dict(row) if row else None
