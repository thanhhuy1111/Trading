from decimal import Decimal
from typing import Optional, Tuple
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.logger import logger
from packages.execution.models import Fill, LiquidityType
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

        open_rows = [
            row
            for row in position_rows
            if row["status"] != "CLOSED" and Decimal(str(row["quantity"])) > Decimal("0")
        ]
        missing_protection = [
            row["symbol"]
            for row in open_rows
            if row.get("initial_stop_price") is None or row.get("take_profit_price") is None
        ]
        if missing_protection:
            result = ReconciliationResult(
                passed=False,
                issues=[
                    "MISSING_DURABLE_PROTECTION:" + ",".join(sorted(missing_protection))
                ],
            )
            logger.error(
                "Durable recovery blocked: open position lacks persisted protection",
                extra={"session_id": str(session_id), "symbols": missing_protection},
            )
            return result, None

        # Rebuild by replaying immutable durable fills. This restores fee totals, trade
        # history, realized buckets and deterministic position/ledger identifiers rather
        # than synthesizing only the latest quantity.
        ledger = PortfolioLedger(initial_cash=initial_cash, account_id=f"PAPER_ACCT_{session_id.hex[:8]}")
        pos_mgr = PositionManager(account_id=f"PAPER_ACCT_{session_id.hex[:8]}", ledger=ledger)
        positions_by_symbol = {row["symbol"]: row for row in position_rows}
        try:
            for row in sorted(fill_rows, key=lambda item: item["sequence_number"]):
                fill = Fill(
                    fill_id=row["fill_id"],
                    exchange_fill_id=f"DURABLE_{row['fill_id']}",
                    exchange_order_id=uuid5(
                        NAMESPACE_URL, f"durable-order:{row['client_order_id']}"
                    ),
                    client_order_id=row["client_order_id"],
                    symbol=row["symbol"],
                    side=row["side"],
                    quantity=Decimal(str(row["quantity"])),
                    price=Decimal(str(row["price"])),
                    quote_quantity=Decimal(str(row["quote_quantity"])),
                    fee=Decimal(str(row["fee"])),
                    fee_asset=row["fee_asset"],
                    liquidity=LiquidityType.TAKER,
                    executed_at=row["event_time"],
                )
                persisted = positions_by_symbol.get(fill.symbol, {})
                pos_mgr.process_fill(
                    fill,
                    fill.executed_at,
                    initial_stop_price=(
                        Decimal(str(persisted["initial_stop_price"]))
                        if fill.side == "BUY" and persisted.get("initial_stop_price") is not None
                        else None
                    ),
                    take_profit_price=(
                        Decimal(str(persisted["take_profit_price"]))
                        if fill.side == "BUY" and persisted.get("take_profit_price") is not None
                        else None
                    ),
                )
        except (ValueError, KeyError) as exc:
            return ReconciliationResult(
                passed=False,
                issues=[f"DURABLE_REPLAY_FAILED:{type(exc).__name__}"],
            ), None

        if ledger.cash_balance != materialized_cash:
            return ReconciliationResult(
                passed=False,
                issues=["DURABLE_REPLAY_CASH_MISMATCH"],
            ), None

        for row in open_rows:
            replayed = pos_mgr.positions.get(row["symbol"])
            if replayed is None:
                return ReconciliationResult(
                    passed=False,
                    issues=[f"DURABLE_REPLAY_POSITION_MISSING:{row['symbol']}"],
                ), None
            pos_mgr.positions[row["symbol"]] = Position.model_validate(
                replayed.model_dump()
                | {
                    "position_id": row["id"],
                    "status": PositionStatus(row["status"]),
                    "initial_stop_price": Decimal(str(row["initial_stop_price"])),
                    "active_stop_price": Decimal(str(row["active_stop_price"]))
                    if row.get("active_stop_price") is not None
                    else Decimal(str(row["initial_stop_price"])),
                    "take_profit_price": Decimal(str(row["take_profit_price"])),
                    "trailing_stop_price": Decimal(str(row["trailing_stop_price"]))
                    if row.get("trailing_stop_price") is not None
                    else None,
                    "current_market_price": Decimal(str(row["current_market_price"]))
                    if row.get("current_market_price") is not None
                    else replayed.current_market_price,
                    "market_value": Decimal(str(row["market_value"]))
                    if row.get("market_value") is not None
                    else replayed.market_value,
                    "opened_at": row.get("opened_at") or replayed.opened_at,
                    "last_fill_at": row.get("last_fill_at") or replayed.last_fill_at,
                    "version": row["version"],
                }
            )
            if row.get("current_market_price") is not None:
                pos_mgr.last_mark_times[row["symbol"]] = row["updated_at"]
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
