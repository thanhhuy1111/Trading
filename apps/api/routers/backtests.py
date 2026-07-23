from datetime import datetime
from decimal import Decimal
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from packages.backtest.datasets import dataset_registry
from packages.backtest.engine import backtest_engine
from packages.backtest.models import (
    BacktestConfig,
    BacktestMode,
    BacktestReport,
    BacktestSession,
    HistoricalDatasetDefinition,
)
from packages.market_data.models import Candle

router = APIRouter(prefix="/backtests", tags=["Backtests"])


class DatasetRegisterRequest(BaseModel):
    name: str
    symbols: List[str]
    timeframes: List[str]
    candles: List[Candle]


class CreateBacktestRequest(BaseModel):
    session_name: str
    dataset_id: UUID
    mode: BacktestMode = BacktestMode.HISTORICAL_REPLAY
    symbols: List[str]
    timeframes: List[str]
    start_time: datetime
    end_time: datetime
    warmup_start_time: datetime
    initial_cash: Decimal = Field(default=Decimal("100000.00"), gt=Decimal("0.0"))
    random_seed: int = 42


@router.post("/datasets/register", response_model=HistoricalDatasetDefinition, status_code=status.HTTP_201_CREATED)
def register_dataset(req: DatasetRegisterRequest) -> HistoricalDatasetDefinition:
    try:
        return dataset_registry.register_dataset(
            name=req.name,
            symbols=req.symbols,
            timeframes=req.timeframes,
            candles=req.candles
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/datasets", response_model=List[HistoricalDatasetDefinition])
def list_datasets() -> List[HistoricalDatasetDefinition]:
    return list(dataset_registry.datasets.values())


@router.get("/datasets/{dataset_id}", response_model=HistoricalDatasetDefinition)
def get_dataset(dataset_id: UUID) -> HistoricalDatasetDefinition:
    ds = dataset_registry.get_dataset(dataset_id)
    if not ds:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return ds


@router.post("", response_model=BacktestSession, status_code=status.HTTP_201_CREATED)
def create_backtest(req: CreateBacktestRequest) -> BacktestSession:
    try:
        config = BacktestConfig(
            session_name=req.session_name,
            mode=req.mode,
            dataset_id=req.dataset_id,
            symbols=req.symbols,
            timeframes=req.timeframes,
            start_time=req.start_time,
            end_time=req.end_time,
            warmup_start_time=req.warmup_start_time,
            initial_cash=req.initial_cash,
            random_seed=req.random_seed
        )
        return backtest_engine.create_session(config)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=List[BacktestSession])
def list_backtests() -> List[BacktestSession]:
    return list(backtest_engine.active_sessions.values())


@router.get("/{session_id}", response_model=BacktestSession)
def get_backtest(session_id: UUID) -> BacktestSession:
    session = backtest_engine.active_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest session not found")
    return session


@router.post("/{session_id}/run", response_model=BacktestReport)
def run_backtest(session_id: UUID) -> BacktestReport:
    try:
        return backtest_engine.run_backtest(session_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
