from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaperSessionStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    WARMING_UP = "WARMING_UP"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class PaperAccountConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    initial_cash: Decimal = Field(default=Decimal("10000.00"), gt=Decimal("0.0"))
    base_currency: str = "USDT"
    allowed_symbols: List[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    maximum_positions: int = 5
    allow_multiple_positions_per_symbol: bool = False


class PaperLatencyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_processing_latency_ms: int = 50
    governance_latency_ms: int = 30
    risk_latency_ms: int = 20
    submission_latency_ms: int = 40
    exchange_ack_latency_ms: int = 60
    cancellation_latency_ms: int = 30
    latency_jitter_ms: int = 15

    @model_validator(mode="after")
    def validate_non_negative(self) -> "PaperLatencyConfig":
        for val in [
            self.signal_processing_latency_ms,
            self.governance_latency_ms,
            self.risk_latency_ms,
            self.submission_latency_ms,
            self.exchange_ack_latency_ms,
            self.cancellation_latency_ms,
            self.latency_jitter_ms,
        ]:
            if val < 0:
                raise ValueError("PAPER_LATENCY_ERROR: Latency parameters cannot be negative")
        return self


class WarmupReadinessReport(BaseModel):
    session_id: UUID
    ready: bool
    required_candles: Dict[str, int]
    available_candles: Dict[str, int]
    feature_readiness: Dict[str, bool]
    regime_ready: bool
    symbol_metadata_ready: bool
    market_stream_healthy: bool
    risk_snapshot_ready: bool
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperTradingSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    name: str
    account_id: str
    status: PaperSessionStatus = PaperSessionStatus.CREATED
    exchange: str = "binance"
    symbols: List[str] = Field(default_factory=lambda: ["BTC/USDT"])
    timeframes: List[str] = Field(default_factory=lambda: ["1h"])
    initial_cash: Decimal = Field(default=Decimal("10000.00"), gt=Decimal("0.0"))
    base_currency: str = "USDT"
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    warmup_start_time: datetime
    ready_at: Optional[datetime] = None
    last_market_event_time: Optional[datetime] = None
    last_processed_event_id: Optional[UUID] = None
    config_snapshot_id: UUID = Field(default_factory=uuid4)
    config_fingerprint: str = ""
    code_version: str = "1.0.0"
    schema_version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperEventJournalEntry(BaseModel):
    journal_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    event_type: str
    event_id: UUID
    source: str
    exchange_event_time: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sequence_number: Optional[int] = None
    payload_checksum: str
    schema_version: int = 1


class PaperCheckpoint(BaseModel):
    checkpoint_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    last_event_time: datetime
    stream_sequence: int
    checkpoint_data: Dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperReport(BaseModel):
    report_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    nav: Decimal
    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    win_rate: Decimal
    trade_count: int
    config_fingerprint: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BacktestPaperComparison(BaseModel):
    comparison_id: UUID = Field(default_factory=uuid4)
    paper_session_id: UUID
    backtest_session_id: UUID
    paper_nav: Decimal
    backtest_nav: Decimal
    nav_diff_pct: Decimal
    slippage_diff_bps: Decimal
    trade_count_diff: int
    compared_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
