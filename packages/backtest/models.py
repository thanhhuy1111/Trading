from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from packages.agents.strategy_config import StrategyConfig, default_strategy_config


class DatasetQualityStatus(str, Enum):
    VALIDATED = "VALIDATED"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


class HistoricalDatasetDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: UUID = Field(default_factory=uuid4)
    name: str
    provider: str = "binance_public"
    exchange: str = "binance"
    symbols: List[str]
    timeframes: List[str]
    start_time: datetime
    end_time: datetime
    candle_count: int = Field(ge=0)
    trade_count: int = Field(ge=0)
    checksum: str
    quality_status: DatasetQualityStatus = DatasetQualityStatus.VALIDATED
    gap_count: int = 0
    duplicate_count: int = 0
    created_at: datetime
    schema_version: int = 1


class BacktestMode(str, Enum):
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    WALK_FORWARD = "WALK_FORWARD"
    ABLATION = "ABLATION"


class BacktestStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INVALID_DATA = "INVALID_DATA"
    REPRODUCIBILITY_FAILED = "REPRODUCIBILITY_FAILED"


class BacktestLiquidityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    maximum_volume_participation_pct: Decimal = Decimal("0.05") # 5% max volume
    minimum_liquidity_notional: Decimal = Decimal("1000.00")
    spread_model: str = "CONSERVATIVE_SPREAD"
    slippage_model: str = "PERCENTAGE_SLIPPAGE"
    market_impact_coefficient: Decimal = Decimal("0.0001")
    allow_partial_fills: bool = True
    same_bar_fill_allowed: bool = False # Default NO_SAME_BAR_FILL


class BacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_name: str
    mode: BacktestMode = BacktestMode.HISTORICAL_REPLAY
    dataset_id: UUID
    symbols: List[str]
    timeframes: List[str]
    start_time: datetime
    end_time: datetime
    warmup_start_time: datetime
    initial_cash: Decimal = Field(default=Decimal("100000.00"), gt=Decimal("0.0"))
    base_currency: str = "USDT"
    feature_set_version: str = "1.0.0"
    agent_versions: Dict[str, str] = Field(default_factory=lambda: {
        "market_regime": "1.0.0",
        "trend": "1.0.0",
        "mean_reversion": "1.0.0",
        "breakout": "1.0.0"
    })
    critic_policy_version: str = "1.0.0"
    allocator_policy_version: str = "1.0.0"
    risk_policy_version: str = "1.0.0"
    execution_policy_version: str = "1.0.0"
    exit_policy_version: str = "1.0.0"
    simulator_version: str = "1.0.0"
    # Versioned agent-parameter set fed into DecisionService for this session. Distinct
    # configs must yield distinct config_checksum fingerprints (see ReproducibilityVerifier)
    # so research-campaign experiments are individually reproducible and auditable.
    strategy_config: StrategyConfig = Field(default_factory=lambda: default_strategy_config)
    random_seed: int = 42
    enable_stop_loss: bool = True
    enable_take_profit: bool = True
    enable_trailing_stop: bool = True
    allow_overlapping_positions: bool = False
    maximum_positions: int = 1
    liquidity_config: BacktestLiquidityConfig = Field(default_factory=BacktestLiquidityConfig)
    schema_version: int = 1


class BacktestSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    name: str
    mode: BacktestMode
    status: BacktestStatus = BacktestStatus.CREATED
    dataset_id: UUID
    dataset_checksum: str
    config_checksum: str
    start_time: datetime
    end_time: datetime
    warmup_start_time: datetime
    replay_time: Optional[datetime] = None
    events_processed: int = 0
    initial_cash: Decimal
    final_nav: Optional[Decimal] = None
    random_seed: int = 42
    code_version: str = "git_sha_placeholder"
    schema_version: int = 1
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TradeEpisode(BaseModel):
    episode_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    position_id: UUID
    symbol: str
    opened_at: datetime
    closed_at: datetime
    entry_quantity: Decimal
    exit_quantity: Decimal
    average_entry_price: Decimal
    average_exit_price: Decimal
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
    maximum_favorable_excursion: Decimal = Decimal("0.0")
    maximum_adverse_excursion: Decimal = Decimal("0.0")
    holding_duration_seconds: int = 0
    exit_reason: str = "UNKNOWN"


class WalkForwardFold(BaseModel):
    fold_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    fold_number: int
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime
    test_nav: Optional[Decimal] = None


class BacktestMetrics(BaseModel):
    session_id: UUID
    initial_nav: Decimal
    final_nav: Decimal
    net_profit: Decimal
    total_return_pct: Decimal
    annualized_return_pct: Optional[Decimal] = None
    max_drawdown_pct: Decimal
    sharpe_ratio: Optional[Decimal] = None
    sortino_ratio: Optional[Decimal] = None
    calmar_ratio: Optional[Decimal] = None
    win_rate: Decimal
    profit_factor: Optional[Decimal] = None
    total_trades: int
    total_fees: Decimal
    total_slippage_cost: Decimal
    created_at: datetime


class BacktestReport(BaseModel):
    report_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    reproducibility_fingerprint: str
    metrics: BacktestMetrics
    dataset_name: str
    dataset_checksum: str
    trade_count: int
    created_at: datetime
