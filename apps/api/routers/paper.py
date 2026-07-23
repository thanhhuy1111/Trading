from datetime import datetime, timezone
from decimal import Decimal
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from packages.paper.comparison import paper_comparison_service
from packages.paper.market_runtime import paper_market_runtime
from packages.paper.models import (
    BacktestPaperComparison,
    PaperSessionStatus,
    PaperTradingSession,
    WarmupReadinessReport,
)
from packages.paper.pipeline import paper_pipeline
from packages.paper.recovery import paper_recovery_service
from packages.paper.session import paper_session_manager
from packages.paper.warmup import warmup_service

router = APIRouter(prefix="/paper-sessions", tags=["paper_trading"])


class CreatePaperSessionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    symbols: List[str] = Field(default_factory=lambda: ["BTC/USDT"])
    timeframes: List[str] = Field(default_factory=lambda: ["1h"])
    initial_cash: Decimal = Field(default=Decimal("10000.00"), gt=Decimal("0.0"))


@router.post("", response_model=PaperTradingSession, status_code=status.HTTP_201_CREATED)
def create_session(req: CreatePaperSessionRequest) -> PaperTradingSession:
    try:
        return paper_session_manager.create_session(
            name=req.name,
            symbols=req.symbols,
            timeframes=req.timeframes,
            initial_cash=req.initial_cash
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=List[PaperTradingSession])
def list_sessions() -> List[PaperTradingSession]:
    return list(paper_session_manager.sessions.values())


@router.get("/{session_id}", response_model=PaperTradingSession)
def get_session(session_id: UUID) -> PaperTradingSession:
    sess = paper_session_manager.sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper session not found")
    return sess


@router.post("/{session_id}/validate", response_model=PaperTradingSession)
def validate_session(session_id: UUID) -> PaperTradingSession:
    try:
        return paper_session_manager.transition_status(
            session_id,
            PaperSessionStatus.VALIDATING,
            reason="User API validation request"
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{session_id}/warmup", response_model=WarmupReadinessReport)
def get_warmup_report(session_id: UUID) -> WarmupReadinessReport:
    sess = paper_session_manager.sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper session not found")

    avail = {sym: 100 for sym in sess.symbols}
    return warmup_service.evaluate_readiness(session_id, avail)


@router.post("/{session_id}/start", response_model=PaperTradingSession)
def start_session(session_id: UUID) -> PaperTradingSession:
    try:
        sess = paper_session_manager.sessions.get(session_id)
        if not sess:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper session not found")

        if sess.status == PaperSessionStatus.CREATED:
            paper_session_manager.transition_status(
                session_id, PaperSessionStatus.VALIDATING, reason="Auto validation"
            )
            paper_session_manager.transition_status(
                session_id, PaperSessionStatus.WARMING_UP, reason="Auto warmup"
            )
            paper_session_manager.transition_status(
                session_id, PaperSessionStatus.READY, reason="Warmup ready"
            )

        sess = paper_session_manager.transition_status(
            session_id, PaperSessionStatus.RUNNING, reason="User API start request"
        )
        paper_market_runtime.start_runtime(session_id)
        return sess
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{session_id}/pause", response_model=PaperTradingSession)
def pause_session(session_id: UUID) -> PaperTradingSession:
    try:
        return paper_session_manager.transition_status(
            session_id, PaperSessionStatus.PAUSED, reason="User API pause request"
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{session_id}/resume", response_model=PaperTradingSession)
def resume_session(session_id: UUID) -> PaperTradingSession:
    try:
        return paper_session_manager.transition_status(
            session_id, PaperSessionStatus.RUNNING, reason="User API resume request"
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{session_id}/stop", response_model=PaperTradingSession)
def stop_session(session_id: UUID) -> PaperTradingSession:
    try:
        sess = paper_session_manager.sessions.get(session_id)
        if not sess:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper session not found")

        if sess.status == PaperSessionStatus.RUNNING:
            paper_session_manager.transition_status(
                session_id, PaperSessionStatus.STOPPING, reason="User API stopping"
            )

        sess = paper_session_manager.transition_status(
            session_id, PaperSessionStatus.STOPPED, reason="User API stop request"
        )
        paper_market_runtime.stop_runtime(session_id)
        return sess
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{session_id}/request-recovery", response_model=PaperTradingSession)
def request_recovery(session_id: UUID) -> PaperTradingSession:
    try:
        sess = paper_session_manager.sessions.get(session_id)
        if not sess:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper session not found")

        if sess.status != PaperSessionStatus.HALTED:
            paper_session_manager.transition_status(
                session_id, PaperSessionStatus.HALTED, reason="Halt for recovery"
            )

        paper_session_manager.transition_status(
            session_id, PaperSessionStatus.RECOVERY_REQUIRED, reason="User API recovery request"
        )
        paper_recovery_service.recover_session(session_id)
        return paper_session_manager.sessions[session_id]
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{session_id}/portfolio")
def get_portfolio(session_id: UUID):
    sess = paper_session_manager.sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper session not found")

    pos_mgr = paper_pipeline.get_position_manager(session_id)
    snap = pos_mgr.get_portfolio_snapshot(datetime.now(timezone.utc))
    return snap.model_dump(mode="json")


@router.get("/{session_id}/compare/{backtest_session_id}", response_model=BacktestPaperComparison)
def compare_with_backtest(session_id: UUID, backtest_session_id: UUID) -> BacktestPaperComparison:
    try:
        return paper_comparison_service.compare_sessions(session_id, backtest_session_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
