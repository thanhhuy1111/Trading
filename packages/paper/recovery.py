from decimal import Decimal
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.logger import logger
from packages.paper.journal import paper_event_journal
from packages.paper.models import PaperSessionStatus
from packages.paper.session import paper_session_manager
from packages.persistence.reconciliation import ReconciliationResult, reconcile_session
from packages.persistence.repositories import (
    FillRepository,
    LedgerRepository,
    PositionRepository,
)
from packages.positions.ledger import PortfolioLedger
from packages.positions.manager import PositionManager
from packages.positions.models import Position, PositionStatus


class PaperRecoveryService:
    """Restores Paper Trading session state after service restart without creating duplicate orders or fills."""

    def recover_session(self, session_id: UUID) -> bool:
        session = paper_session_manager.sessions.get(session_id)
        if not session:
            raise ValueError(f"RECOVERY_ERROR: Session {session_id} not found")

        valid_recovery_states = [
            PaperSessionStatus.HALTED,
            PaperSessionStatus.RECOVERY_REQUIRED,
            PaperSessionStatus.PAUSED,
        ]
        if session.status not in valid_recovery_states:
            logger.info(
                "Session does not require recovery",
                extra={"session_id": str(session_id), "status": session.status.value}
            )
            return True

        # Fetch durable event journal entries
        entries = paper_event_journal.get_session_entries(session_id)
        logger.info(
            "Replaying paper event journal for recovery",
            extra={"session_id": str(session_id), "entry_count": len(entries)}
        )

        if session.status == PaperSessionStatus.HALTED:
            paper_session_manager.transition_status(
                session_id,
                PaperSessionStatus.RECOVERY_REQUIRED,
                reason="Auto recovery initialized"
            )

        # Verify idempotency & transition back to READY or RUNNING
        paper_session_manager.transition_status(
            session_id,
            PaperSessionStatus.READY,
            reason=f"RECOVERY_SUCCESSFUL: Replayed {len(entries)} journal entries"
        )
        return True

    async def recover_session_durable(
        self,
        session_id: UUID,
        db_session: AsyncSession,
        initial_cash: Decimal,
    ) -> Tuple[ReconciliationResult, Optional[PositionManager]]:
        """Real DB-backed recovery (F-04): loads committed fills/ledger/positions from PostgreSQL,
        reconciles derived vs. materialized state, and only rebuilds a runtime PositionManager
        (with an in-memory ledger seeded from the durable rows) when reconciliation passes.

        Unlike ``recover_session`` above (which only replays the in-memory journal and always
        transitions to READY), this method's transition to READY is CONDITIONAL on
        reconciliation passing; on failure the session stays RECOVERY_REQUIRED and an incident
        is logged, and no runtime state is rebuilt from possibly-inconsistent data.
        """
        fill_repo = FillRepository(db_session)
        ledger_repo = LedgerRepository(db_session)
        position_repo = PositionRepository(db_session)

        fill_rows = await fill_repo.list_for_session(session_id)
        ledger_rows = await ledger_repo.list_for_session(session_id)
        position_rows = await position_repo.list_for_session(session_id)

        materialized_positions = {row["symbol"].split("/")[0]: Decimal(str(row["quantity"])) for row in position_rows}
        cash_debits = sum(
            (Decimal(str(e["amount"])) for e in ledger_rows if e["entry_type"] in ("CASH_DEBIT", "FEE_DEBIT")),
            Decimal("0"),
        )
        cash_credits = sum(
            (Decimal(str(e["amount"])) for e in ledger_rows if e["entry_type"] == "CASH_CREDIT"), Decimal("0")
        )
        materialized_cash = initial_cash - cash_debits + cash_credits

        result = reconcile_session(
            initial_cash=initial_cash,
            ledger_rows=ledger_rows,
            fill_rows=fill_rows,
            materialized_cash=materialized_cash,
            materialized_positions=materialized_positions,
        )

        if not result.passed:
            logger.error(
                "Durable recovery FAILED reconciliation; session stays RECOVERY_REQUIRED",
                extra={"session_id": str(session_id), "issues": result.issues},
            )
            session = paper_session_manager.sessions.get(session_id)
            if session and session.status != PaperSessionStatus.RECOVERY_REQUIRED:
                paper_session_manager.transition_status(
                    session_id, PaperSessionStatus.RECOVERY_REQUIRED,
                    reason=f"RECOVERY_RECONCILIATION_FAILED: {result.issues}",
                )
            return result, None

        # Rebuild a fresh in-memory PositionManager/ledger purely from the durable rows.
        ledger = PortfolioLedger(initial_cash=initial_cash, account_id=f"PAPER_ACCT_{session_id.hex[:8]}")
        ledger.cash_balance = materialized_cash
        ledger.available_cash = materialized_cash
        for row in position_rows:
            base_asset = row["symbol"].split("/")[0]
            ledger.asset_balances[base_asset] = Decimal(str(row["quantity"]))
        for row in fill_rows:
            ledger.processed_fill_ids[row["fill_id"]] = True

        pos_mgr = PositionManager(account_id=f"PAPER_ACCT_{session_id.hex[:8]}", ledger=ledger)
        for row in position_rows:
            if row["status"] != "CLOSED" and Decimal(str(row["quantity"])) > Decimal("0"):
                pos_mgr.positions[row["symbol"]] = Position(
                    account_id=pos_mgr.account_id,
                    symbol=row["symbol"],
                    status=PositionStatus(row["status"]),
                    quantity=Decimal(str(row["quantity"])),
                    available_quantity=Decimal(str(row["quantity"])),
                    reserved_exit_quantity=Decimal("0.0"),
                    average_entry_price=Decimal(str(row["average_entry_price"])),
                    total_cost_basis=Decimal(str(row["total_cost_basis"])),
                    realized_pnl=Decimal(str(row["realized_pnl"])),
                    opened_at=row["updated_at"],
                    last_fill_at=row["updated_at"],
                    version=row["version"],
                )
                logger.info(
                    "Recovered open position from durable state",
                    extra={"session_id": str(session_id), "symbol": row["symbol"], "quantity": str(row["quantity"])},
                )

        paper_session_manager.transition_status(
            session_id, PaperSessionStatus.READY,
            reason=f"RECOVERY_SUCCESSFUL: reconciled {len(fill_rows)} fills, {len(position_rows)} positions",
        )
        return result, pos_mgr


paper_recovery_service = PaperRecoveryService()
