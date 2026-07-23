"""Typed lineage/metadata records for the research pipeline.

Bulk numeric data (per-candle features, per-observation labels) is handled as pandas
DataFrames, not per-row Pydantic models -- instantiating a Pydantic model per row for a
multi-year, multi-timeframe dataset does not scale and the repository already uses
pandas/numpy/polars as core dependencies. Every DataFrame produced by this package is
paired with one of the typed metadata records below, persisted alongside it by
`packages.research.artifacts`, so lineage is always traceable even though the bulk data
itself is tabular.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class DatasetQualityStatus(str, Enum):
    VALIDATED = "VALIDATED"
    DEGRADED = "DEGRADED"


class RawCandleDataset(BaseModel):
    """Metadata for a raw, validated, closed-candle dataset (packages.research.dataset_builder)."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_checksum: str
    symbols: List[str]
    timeframes: List[str]
    start_time: datetime
    end_time: datetime
    candle_count: int
    source: str
    source_version: str
    created_at: datetime
    code_commit: str
    config_hash: str
    duplicate_count: int = 0
    rejected_count: int = 0
    quality_status: DatasetQualityStatus = DatasetQualityStatus.VALIDATED
    quality_issues: List[str] = Field(default_factory=list)
    schema_version: int = 1


class TrainingDataset(BaseModel):
    """Metadata for the joined feature+label table built from a RawCandleDataset
    (packages.research.feature_dataset + packages.research.labels)."""

    model_config = ConfigDict(frozen=True)

    training_dataset_id: str = Field(default_factory=lambda: str(uuid4()))
    source_dataset_id: str
    source_dataset_checksum: str
    table_checksum: str
    feature_version: str
    label_version: str
    symbols: List[str]
    timeframes: List[str]
    horizons_minutes: List[int]
    row_count: int
    feature_columns: List[str]
    created_at: datetime
    code_commit: str
    config_hash: str
    schema_version: int = 1


class SplitWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str  # "train" | "validation" | "test"
    start: datetime
    end: datetime


class WalkForwardWindowPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    fold_number: int
    train: SplitWindow
    validation: SplitWindow
    test: SplitWindow
    purge_hours: int
    embargo_hours: int


class ModelArtifactRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str = Field(default_factory=lambda: str(uuid4()))
    model_type: str
    model_version: str
    feature_version: str
    dataset_checksum: str
    label_version: str
    hyperparameters: Dict[str, Any]
    random_seed: int
    train_period: str
    validation_period: str
    test_period: str
    code_commit: str
    artifact_path: str
    artifact_checksum: str
    config_hash: str
    created_at: datetime
    schema_version: int = 1


class CalibrationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    fit_on: str = "validation_only"
    sample_size: int
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    calibration_score: float
    reliability_buckets: List[Dict[str, float]]


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_count: int
    win_rate: Optional[Decimal] = None
    net_pnl_bps: Optional[Decimal] = None
    average_net_return_bps: Optional[Decimal] = None
    expectancy_bps: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None
    sharpe: Optional[Decimal] = None
    sortino: Optional[Decimal] = None
    calmar: Optional[Decimal] = None
    max_drawdown_pct: Optional[Decimal] = None
    turnover: Optional[Decimal] = None
    total_fees_bps: Optional[Decimal] = None
    total_slippage_bps: Optional[Decimal] = None
    average_holding_minutes: Optional[Decimal] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    roc_auc: Optional[float] = None
    brier_score: Optional[float] = None
    log_loss: Optional[float] = None


class EvaluationBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str  # "symbol" | "timeframe" | "regime" | "probability_bucket" | "window"
    key: str
    metrics: EvaluationMetrics


class EvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluation_id: str = Field(default_factory=lambda: str(uuid4()))
    subject_name: str  # model_version or baseline name, e.g. "logreg_v1" / "BUY_AND_HOLD"
    subject_type: str  # "MODEL" | "BASELINE"
    dataset_checksum: str
    walk_forward_windows: int
    aggregate_metrics: EvaluationMetrics
    breakdowns: List[EvaluationBreakdown]
    calibration: Optional[CalibrationReport] = None
    experiments_tried: int = 1
    deflated_sharpe_ratio: Optional[float] = None
    probability_of_backtest_overfitting: Optional[float] = None
    multiple_testing_warning: Optional[str] = None
    created_at: datetime
    code_commit: str
    config_hash: str
    schema_version: int = 1
