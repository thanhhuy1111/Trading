"""Atomic fill-commit orchestration + DB-backed idempotency (F-04).

The orchestration LOGIC (step order, rollback-on-failure, IntegrityError -> idempotent result)
is verified by unit tests using a fake ops object. The SQLAlchemy implementation is authored but
NOT executed against PostgreSQL in this environment (IMPLEMENTED_NOT_VERIFIED).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError

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
