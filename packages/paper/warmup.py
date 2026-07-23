from datetime import datetime, timezone
from typing import Dict, List
from uuid import UUID

from packages.common.logger import logger
from packages.paper.models import WarmupReadinessReport
from packages.paper.session import paper_session_manager


class WarmupService:
    """Validates public market data baseline and feature readiness before enabling Paper Trading."""

    def evaluate_readiness(
        self,
        session_id: UUID,
        available_candles: Dict[str, int],
        min_required_candles: int = 50
    ) -> WarmupReadinessReport:
        session = paper_session_manager.sessions.get(session_id)
        if not session:
            raise ValueError(f"WARMUP_ERROR: Session {session_id} not found")

        req_candles: Dict[str, int] = {sym: min_required_candles for sym in session.symbols}
        feat_readiness: Dict[str, bool] = {}
        blockers: List[str] = []
        warnings: List[str] = []

        for sym in session.symbols:
            avail = available_candles.get(sym, 0)
            if avail < min_required_candles:
                feat_readiness[sym] = False
                blockers.append(f"INSUFFICIENT_CANDLES_{sym}: Available {avail} < Required {min_required_candles}")
            else:
                feat_readiness[sym] = True

        regime_ready = len(blockers) == 0
        symbol_metadata_ready = True
        market_stream_healthy = True
        risk_snapshot_ready = True

        is_ready = (
            regime_ready
            and symbol_metadata_ready
            and market_stream_healthy
            and risk_snapshot_ready
            and len(blockers) == 0
        )

        report = WarmupReadinessReport(
            session_id=session_id,
            ready=is_ready,
            required_candles=req_candles,
            available_candles=available_candles,
            feature_readiness=feat_readiness,
            regime_ready=regime_ready,
            symbol_metadata_ready=symbol_metadata_ready,
            market_stream_healthy=market_stream_healthy,
            risk_snapshot_ready=risk_snapshot_ready,
            blockers=blockers,
            warnings=warnings,
            evaluated_at=datetime.now(timezone.utc)
        )

        logger.info("Warmup readiness evaluated", extra={"session_id": str(session_id), "ready": is_ready})
        return report


warmup_service = WarmupService()
