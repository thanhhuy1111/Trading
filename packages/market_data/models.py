from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class DataQualityStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    STALE = "STALE"
    RESYNCING = "RESYNCING"
    UNKNOWN = "UNKNOWN"


class RecommendedAction(str, Enum):
    CONTINUE = "CONTINUE"
    DEGRADE_FEATURES = "DEGRADE_FEATURES"
    PAUSE_SYMBOL = "PAUSE_SYMBOL"
    PAUSE_MARKET_DATA = "PAUSE_MARKET_DATA"
    RESYNC = "RESYNC"
    CREATE_INCIDENT = "CREATE_INCIDENT"


class BaseMarketDataModel(BaseModel):
    """Base class enforcing mandatory metadata across all market data models."""

    exchange: str
    symbol: str
    exchange_timestamp: datetime
    received_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    schema_version: int = 1
    source: str = "binance_public"
    data_quality_status: DataQualityStatus = DataQualityStatus.HEALTHY

    @model_validator(mode="after")
    def validate_timestamps(self):
        if self.exchange_timestamp.tzinfo is None:
            raise ValueError("exchange_timestamp must be timezone-aware UTC")
        if self.received_timestamp.tzinfo is None:
            raise ValueError("received_timestamp must be timezone-aware UTC")
        return self


class ExchangeInfo(BaseModel):
    exchange_id: str
    name: str
    is_active: bool = True
    rate_limits: Dict[str, Any] = Field(default_factory=dict)
    supported_timeframes: List[Timeframe] = Field(
        default_factory=lambda: [
            Timeframe.M1,
            Timeframe.M5,
            Timeframe.M15,
            Timeframe.H1,
            Timeframe.H4,
        ]
    )


class SymbolInfo(BaseModel):
    canonical_symbol: str  # e.g., BTC/USDT
    exchange_symbol: str  # e.g., BTCUSDT
    exchange: str
    base_asset: str  # e.g., BTC
    quote_asset: str  # e.g., USDT
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    status: str = "TRADING"
    trading_permissions: List[str] = Field(default_factory=lambda: ["SPOT"])
    metadata_version: int = 1
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class MarketTrade(BaseMarketDataModel):
    trade_id: str
    price: Decimal
    quantity: Decimal
    side: str  # BUY or SELL
    is_buyer_maker: bool = False

    @model_validator(mode="after")
    def validate_positive_values(self):
        if self.price <= Decimal("0"):
            raise ValueError("Trade price must be strictly positive (> 0)")
        if self.quantity <= Decimal("0"):
            raise ValueError("Trade quantity must be strictly positive (> 0)")
        return self


class Candle(BaseMarketDataModel):
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    quote_volume: Decimal = Decimal("0")
    trades_count: int = 0
    is_closed: bool = True

    @model_validator(mode="after")
    def validate_ohlc_integrity(self):
        if self.open_price <= Decimal("0") or self.close_price <= Decimal("0"):
            raise ValueError("Candle prices must be strictly positive (> 0)")
        if self.high_price < max(self.open_price, self.close_price, self.low_price):
            raise ValueError("Candle high_price must be >= open, close, and low prices")
        if self.low_price > min(self.open_price, self.close_price, self.high_price):
            raise ValueError("Candle low_price must be <= open, close, and high prices")
        if self.volume < Decimal("0"):
            raise ValueError("Candle volume cannot be negative")
        return self


class CandleUpdate(BaseMarketDataModel):
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    current_price: Decimal
    volume: Decimal
    is_closed: bool = False


class OrderBookLevel(BaseModel):
    price: Decimal
    quantity: Decimal


class OrderBookSnapshot(BaseMarketDataModel):
    sequence_id: int
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]

    @model_validator(mode="after")
    def validate_order_book(self):
        if self.bids and self.asks:
            best_bid = self.bids[0].price
            best_ask = self.asks[0].price
            if best_bid >= best_ask:
                raise ValueError(
                    f"Crossed order book detected: best_bid ({best_bid}) >= best_ask ({best_ask})"
                )
        return self


class OrderBookDelta(BaseMarketDataModel):
    first_update_id: int
    final_update_id: int
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]


class BestBidAsk(BaseMarketDataModel):
    best_bid_price: Decimal
    best_bid_quantity: Decimal
    best_ask_price: Decimal
    best_ask_quantity: Decimal


class MarketDataEnvelope(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    data_type: str  # trade, candle, order_book
    payload: Dict[str, Any]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class MarketDataHealth(BaseModel):
    exchange: str
    symbol: str
    trades_status: DataQualityStatus = DataQualityStatus.HEALTHY
    candles_status: DataQualityStatus = DataQualityStatus.HEALTHY
    order_book_status: DataQualityStatus = DataQualityStatus.HEALTHY
    overall_status: DataQualityStatus = DataQualityStatus.HEALTHY
    last_trade_at: Optional[datetime] = None
    last_candle_at: Optional[datetime] = None
    last_order_book_at: Optional[datetime] = None
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DataQualityIssue(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    exchange: str
    symbol: str
    data_type: str
    issue_code: str
    message: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    is_resolved: bool = False


class DataQualityResult(BaseModel):
    is_healthy: bool
    status: DataQualityStatus
    issues: List[DataQualityIssue] = Field(default_factory=list)
    recommended_action: RecommendedAction = RecommendedAction.CONTINUE


class SequenceGap(BaseModel):
    symbol: str
    expected_sequence: int
    received_sequence: int
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class IngestionCheckpoint(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    exchange: str
    symbol: str
    timeframe: Timeframe
    last_ingested_open_time: datetime
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
