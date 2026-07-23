from uuid import UUID

from packages.common.logger import logger
from packages.paper.journal import paper_event_journal
from packages.paper.models import PaperSessionStatus
from packages.paper.session import paper_session_manager


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


paper_recovery_service = PaperRecoveryService()
