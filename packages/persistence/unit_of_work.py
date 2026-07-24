"""Atomic fill-commit orchestration + DB-backed idempotency (F-04).

The orchestration LOGIC (step order, rollback-on-failure, IntegrityError -> idempotent result)
is verified by unit tests using a fake ops object. The SQLAlchemy implementation is authored but
NOT executed against PostgreSQL in this environment (IMPLEMENTED_NOT_VERIFIED).
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.execution.models import Fill
from packages.persistence.repositories import (
    FillRepository,
    LedgerRepository,
    OrderRepository,
    PnLBucketRepository,
    PositionRepository,
    RiskStateRepository,
)
from packages.positions.manager import PositionManager
from packages.positions.models import PositionStatus

# Mandated order for committing one fill; a single DB transaction wraps all of it.
FILL_COMMIT_STEP_ORDER: List[str] = [
    "insert_fill",
    "insert_ledger_entries",
    "upsert_position",
    "update_pnl_bucket",
    "update_risk_state",
    "append_journal",
    "mark_order_filled",
    "commit",
]


@dataclass
class FillCommitResult:
    fill_id: UUID
    committed: bool           # newly committed this call
    idempotent_replay: bool   # the fill already existed; no state mutated
    steps: List[str] = field(default_factory=list)


class FillTxnOps(Protocol):
    """Discrete operations the orchestrator runs inside ONE transaction."""

    async def fill_already_committed(self, fill_id: UUID) -> bool: ...
    async def insert_fill(self, fill: object) -> None: ...            # may raise IntegrityError on dup fill_id
    async def insert_ledger_entries(self, fill: object) -> None: ...
    async def upsert_position(self, fill: object) -> None: ...
    async def update_pnl_bucket(self, fill: object, realized_pnl: Decimal) -> None: ...
    async def update_risk_state(self, fill: object) -> None: ...
    async def append_journal(self, fill: object) -> None: ...
    async def mark_order_filled(self, fill: object) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class FillCommitOrchestrator:
    """Commits a fill and all derived accounting in a single atomic transaction.

    Guarantees:
    - Either every step commits or the whole transaction is rolled back (no partial state).
    - A duplicate ``fill_id`` (fast-path check OR unique-constraint IntegrityError) yields an
      idempotent result with NO second debit/credit/position/PnL mutation.
    """

    async def commit_fill(
        self,
        ops: FillTxnOps,
        fill: object,
        realized_pnl: Decimal = Decimal("0"),
    ) -> FillCommitResult:
        fill_id = fill.fill_id  # type: ignore[attr-defined]

        # Fast-path idempotency: already committed -> no-op replay.
        if await ops.fill_already_committed(fill_id):
            return FillCommitResult(fill_id=fill_id, committed=False, idempotent_replay=True,
                                    steps=["idempotent_precheck"])

        steps: List[str] = []
        try:
            await ops.insert_fill(fill)
            steps.append("insert_fill")
            await ops.insert_ledger_entries(fill)
            steps.append("insert_ledger_entries")
            await ops.upsert_position(fill)
            steps.append("upsert_position")
            await ops.update_pnl_bucket(fill, realized_pnl)
            steps.append("update_pnl_bucket")
            await ops.update_risk_state(fill)
            steps.append("update_risk_state")
            await ops.append_journal(fill)
            steps.append("append_journal")
            await ops.mark_order_filled(fill)
            steps.append("mark_order_filled")
            await ops.commit()
            steps.append("commit")
            return FillCommitResult(fill_id=fill_id, committed=True, idempotent_replay=False, steps=steps)
        except IntegrityError:
            # Lost the race on the unique fill_id constraint: another committer already won.
            await ops.rollback()
            steps.append("rollback_integrity")
            return FillCommitResult(fill_id=fill_id, committed=False, idempotent_replay=True, steps=steps)
        except Exception:
            # Any other failure: roll back the entire transaction (no partial state) and surface.
            await ops.rollback()
            steps.append("rollback_error")
            raise


fill_commit_orchestrator = FillCommitOrchestrator()


class SqlAlchemyFillTxnOps:
    """Real PostgreSQL binding of ``FillTxnOps`` (F-04).

    Domain accounting (ledger entries, position quantity/avg-cost, realized PnL) is computed
    exactly once via the same tested ``PortfolioLedger``/``PositionManager`` logic used
    elsewhere in the codebase, then persisted step-by-step inside the orchestrator's single
    transaction. The in-memory ``position_manager`` passed in is mutated too, so it stays a
    correct read cache of what was just durably committed (never re-derives from the ledger a
    second time, which would double count).
    """

    def __init__(
        self,
        session: AsyncSession,
        session_id: UUID,
        position_manager: PositionManager,
        initial_stop_price: Optional[Decimal] = None,
        take_profit_price: Optional[Decimal] = None,
    ) -> None:
        self.session = session
        self.session_id = session_id
        self.position_manager = position_manager
        self.fill_repo = FillRepository(session)
        self.ledger_repo = LedgerRepository(session)
        self.position_repo = PositionRepository(session)
        self.pnl_repo = PnLBucketRepository(session)
        self.risk_repo = RiskStateRepository(session)
        self.order_repo = OrderRepository(session)
        self._entries: List = []
        self._pnl_entry = None
        self._position = None
        self.initial_stop_price = initial_stop_price
        self.take_profit_price = take_profit_price
        self._memory_snapshot = None

    async def fill_already_committed(self, fill_id: UUID) -> bool:
        return await self.fill_repo.exists(fill_id)

    async def insert_fill(self, fill: Fill) -> None:
        await self.fill_repo.insert(fill, self.session_id)

    async def insert_ledger_entries(self, fill: Fill) -> None:
        # Domain calculation (pure, deterministic): compute ledger entries once here.
        self._memory_snapshot = deepcopy(self.position_manager.__dict__)
        pos_before = self.position_manager.positions.get(fill.symbol)
        if fill.side == "SELL" and (
            pos_before is None
            or pos_before.status == PositionStatus.CLOSED
            or fill.quantity > pos_before.available_quantity
        ):
            raise ValueError(
                "INSUFFICIENT_POSITION_QUANTITY: durable SELL exceeds available LONG position"
            )
        if pos_before is not None and fill.executed_at < pos_before.last_fill_at:
            raise ValueError("OUT_OF_ORDER_FILL: durable fill predates position state")
        if (
            fill.side == "BUY"
            and (pos_before is None or pos_before.status == PositionStatus.CLOSED)
            and (self.initial_stop_price is None or self.take_profit_price is None)
        ):
            raise ValueError(
                "MISSING_DURABLE_PROTECTION: BUY requires approved stop and take-profit"
            )
        avg_entry = pos_before.average_entry_price if pos_before else Decimal("0.0")
        entries, pnl_entry = self.position_manager.ledger.process_fill(
            fill,
            fill.executed_at,
            avg_entry,
            pos_before.position_id if pos_before is not None else None,
        )
        self._entries = entries
        self._pnl_entry = pnl_entry
        await self.ledger_repo.insert_entries(
            self.session_id,
            fill.fill_id,
            [
                {
                    "entry_id": e.entry_id,
                    "asset": e.asset,
                    "entry_type": e.entry_type.value,
                    "amount": e.amount,
                    "currency": e.asset,
                    "event_time": e.effective_at,
                }
                for e in entries
            ],
        )

    async def upsert_position(self, fill: Fill) -> None:
        # Applies the SAME entries/pnl_entry already persisted above — never re-touches the ledger.
        pos, _ = self.position_manager.apply_fill_accounting(
            fill,
            self._entries,
            self._pnl_entry,
            initial_stop_price=self.initial_stop_price,
            take_profit_price=self.take_profit_price,
        )
        self._position = pos
        await self.position_repo.upsert(
            self.session_id,
            fill.symbol,
            pos.quantity,
            pos.average_entry_price,
            pos.total_cost_basis,
            self._pnl_entry.realized_pnl if self._pnl_entry else Decimal("0"),
            pos.status.value if hasattr(pos.status, "value") else str(pos.status),
            position_id=pos.position_id,
            total_fees=pos.total_fees,
            initial_stop_price=pos.initial_stop_price,
            active_stop_price=pos.active_stop_price,
            take_profit_price=pos.take_profit_price,
            trailing_stop_price=pos.trailing_stop_price,
            current_market_price=pos.current_market_price,
            market_value=pos.market_value,
            opened_at=pos.opened_at,
            last_fill_at=pos.last_fill_at,
        )

    async def update_pnl_bucket(self, fill: Fill, realized_pnl: Decimal) -> None:
        if not self._pnl_entry:
            return
        pnl = self._pnl_entry.realized_pnl
        fee = self._pnl_entry.exit_fee
        et = fill.executed_at
        day_start = et.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        week_start = day_start - timedelta(days=day_start.weekday())
        week_end = week_start + timedelta(days=7)
        await self.pnl_repo.add_realized_pnl(self.session_id, "DAILY", day_start, day_end, pnl, fee)
        await self.pnl_repo.add_realized_pnl(self.session_id, "WEEKLY", week_start, week_end, pnl, fee)

    async def update_risk_state(self, fill: Fill) -> None:
        snap = self.position_manager.get_portfolio_snapshot(fill.executed_at)
        await self.risk_repo.upsert(self.session_id, "NORMAL", snap.equity_peak, snap.drawdown_pct)

    async def append_journal(self, fill: Fill) -> None:
        # Round-4 scope: the durable journal table (paper_event_journal) already exists
        # (migration 010); wiring fill-commit journal entries into it is deferred to the
        # ingestion-worker integration pass. No-op here (does not affect atomicity: the fill,
        # ledger, position, PnL, and risk-state rows above are still committed/rolled back together).
        return

    async def mark_order_filled(self, fill: Fill) -> None:
        await self.order_repo.mark_filled(self.session_id, fill.client_order_id, fill.quantity)

    async def commit(self) -> None:
        await self.session.commit()
        self._memory_snapshot = None

    async def rollback(self) -> None:
        await self.session.rollback()
        if self._memory_snapshot is not None:
            self.position_manager.__dict__.clear()
            self.position_manager.__dict__.update(self._memory_snapshot)
            self._memory_snapshot = None
