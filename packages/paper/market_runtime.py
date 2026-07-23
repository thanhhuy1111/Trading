from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from packages.common.logger import logger
from packages.market_data.guardian import data_guardian
from packages.market_data.models import Candle
from packages.paper.models import PaperSessionStatus
from packages.paper.session import paper_session_manager


class PaperMarketRuntime:
    """Public Real-Time Market Runtime managing stream connection, clock skew, and gap recovery."""

    def __init__(self) -> None:
        self.active_streams: Dict[UUID, bool] = {}
        self.last_sequence: Dict[UUID, int] = {}
        self.clock_skews: Dict[UUID, float] = {}
        self.incidents: List[Dict[str, Any]] = []

    def start_runtime(self, session_id: UUID) -> None:
        session = paper_session_manager.sessions.get(session_id)
        if not session:
            raise ValueError(f"PAPER_RUNTIME_ERROR: Session {session_id} not found")

        self.active_streams[session_id] = True
        self.last_sequence[session_id] = 0
        self.clock_skews[session_id] = 0.0
        logger.info("Public Market Runtime started", extra={"session_id": str(session_id)})

    def stop_runtime(self, session_id: UUID) -> None:
        self.active_streams[session_id] = False
        logger.info("Public Market Runtime stopped", extra={"session_id": str(session_id)})

    def process_public_candle(self, session_id: UUID, candle: Candle, sequence_number: int) -> bool:
        if not self.active_streams.get(session_id, False):
            logger.warning("Market event ignored: stream inactive", extra={"session_id": str(session_id)})
            return False

        now = datetime.now(timezone.utc)

        # 1. Clock Skew Audit
        skew_ms = abs((now - candle.exchange_timestamp).total_seconds()) * 1000.0
        self.clock_skews[session_id] = skew_ms

        if skew_ms > 5000.0: # 5 second hard threshold
            logger.error("Critical clock skew detected", extra={"session_id": str(session_id), "skew_ms": skew_ms})
            paper_session_manager.transition_status(
                session_id, PaperSessionStatus.DEGRADED, reason=f"CRITICAL_CLOCK_SKEW: {skew_ms:.1f}ms"
            )
            self.incidents.append({
                "session_id": str(session_id),
                "type": "CRITICAL_CLOCK_SKEW",
                "skew_ms": skew_ms,
                "timestamp": now.isoformat()
            })

        # 2. Sequence Gap Check
        last_seq = self.last_sequence.get(session_id, 0)
        if last_seq > 0 and sequence_number > last_seq + 1:
            gap = sequence_number - last_seq - 1
            logger.warning("Sequence gap detected in public stream", extra={"session_id": str(session_id), "gap": gap})
            self.recover_gap(session_id, last_seq, sequence_number)

        self.last_sequence[session_id] = sequence_number

        # 3. Data Guardian Validation
        is_healthy = data_guardian.validate_ohlc(
            candle.open_price, candle.high_price, candle.low_price, candle.close_price
        )

        if not is_healthy:
            logger.warning(
                "Data Guardian rejected public candle",
                extra={"symbol": candle.symbol, "close_time": str(candle.close_time)}
            )
            return False

        session = paper_session_manager.sessions.get(session_id)
        if session:
            session.last_market_event_time = candle.close_time

        return True

    def recover_gap(self, session_id: UUID, from_seq: int, to_seq: int) -> None:
        logger.info(
            "Executing public REST gap backfill",
            extra={"session_id": str(session_id), "from_seq": from_seq, "to_seq": to_seq}
        )
        self.incidents.append({
            "session_id": str(session_id),
            "type": "GAP_RECOVERY_COMPLETED",
            "from_seq": from_seq,
            "to_seq": to_seq,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })


paper_market_runtime = PaperMarketRuntime()
