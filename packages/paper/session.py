from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from packages.common.logger import logger
from packages.paper.models import (
    PaperAccountConfig,
    PaperSessionStatus,
    PaperTradingSession,
)


class PaperSessionManager:
    """Manages paper trading session lifecycle and strict state transitions."""

    VALID_TRANSITIONS: Dict[PaperSessionStatus, List[PaperSessionStatus]] = {
        PaperSessionStatus.CREATED: [PaperSessionStatus.VALIDATING],
        PaperSessionStatus.VALIDATING: [PaperSessionStatus.WARMING_UP, PaperSessionStatus.FAILED],
        PaperSessionStatus.WARMING_UP: [
            PaperSessionStatus.READY,
            PaperSessionStatus.DEGRADED,
            PaperSessionStatus.FAILED,
        ],
        PaperSessionStatus.READY: [PaperSessionStatus.RUNNING, PaperSessionStatus.STOPPED],
        PaperSessionStatus.RUNNING: [
            PaperSessionStatus.PAUSED,
            PaperSessionStatus.DEGRADED,
            PaperSessionStatus.HALTED,
            PaperSessionStatus.STOPPING,
            PaperSessionStatus.FAILED,
        ],
        PaperSessionStatus.PAUSED: [PaperSessionStatus.RUNNING, PaperSessionStatus.STOPPING, PaperSessionStatus.HALTED],
        PaperSessionStatus.DEGRADED: [PaperSessionStatus.RUNNING, PaperSessionStatus.HALTED, PaperSessionStatus.FAILED],
        PaperSessionStatus.HALTED: [PaperSessionStatus.RECOVERY_REQUIRED],
        PaperSessionStatus.RECOVERY_REQUIRED: [PaperSessionStatus.READY, PaperSessionStatus.FAILED],
        PaperSessionStatus.STOPPING: [PaperSessionStatus.STOPPED],
        PaperSessionStatus.STOPPED: [],
        PaperSessionStatus.FAILED: [],
    }

    def __init__(self) -> None:
        self.sessions: Dict[UUID, PaperTradingSession] = {}
        self.account_configs: Dict[UUID, PaperAccountConfig] = {}
        self.transition_logs: List[Dict[str, Any]] = []

    def create_session(
        self,
        name: str,
        symbols: List[str],
        timeframes: List[str],
        initial_cash: Decimal = Decimal("10000.00"),
        warmup_start_time: Optional[datetime] = None
    ) -> PaperTradingSession:
        session_id = uuid4()
        account_id = f"PAPER_ACCT_{session_id.hex[:8]}"

        w_start = warmup_start_time or datetime.now(timezone.utc)

        session = PaperTradingSession(
            session_id=session_id,
            name=name,
            account_id=account_id,
            status=PaperSessionStatus.CREATED,
            symbols=symbols,
            timeframes=timeframes,
            initial_cash=initial_cash,
            warmup_start_time=w_start,
            config_fingerprint=f"CFG_{session_id.hex[:12]}"
        )

        acct_cfg = PaperAccountConfig(
            account_id=account_id,
            initial_cash=initial_cash,
            allowed_symbols=symbols
        )

        self.sessions[session_id] = session
        self.account_configs[session_id] = acct_cfg
        logger.info("Created PaperTradingSession", extra={"session_id": str(session_id), "account_id": account_id})
        return session

    def transition_status(
        self,
        session_id: UUID,
        to_status: PaperSessionStatus,
        reason: str = "Lifecycle event"
    ) -> PaperTradingSession:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"PAPER_SESSION_ERROR: Session {session_id} not found")

        current = session.status
        allowed = self.VALID_TRANSITIONS.get(current, [])

        if to_status not in allowed:
            raise ValueError(
                f"INVALID_STATUS_TRANSITION: Cannot transition from {current.value} "
                f"to {to_status.value}. Reason: {reason}"
            )

        session.status = to_status
        now = datetime.now(timezone.utc)

        if to_status == PaperSessionStatus.RUNNING and session.started_at is None:
            session.started_at = now
        elif to_status == PaperSessionStatus.STOPPED:
            session.stopped_at = now
        elif to_status == PaperSessionStatus.READY:
            session.ready_at = now

        self.transition_logs.append({
            "session_id": str(session_id),
            "from_status": current.value,
            "to_status": to_status.value,
            "reason": reason,
            "timestamp": now.isoformat()
        })

        logger.info(
            "Paper session status transition",
            extra={"session_id": str(session_id), "from": current.value, "to": to_status.value}
        )
        return session


paper_session_manager = PaperSessionManager()
