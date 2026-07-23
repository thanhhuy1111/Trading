from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Tuple

from pydantic import BaseModel, Field


class MarketTick(BaseModel):
    """Real-time market tick event."""
    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    exchange: str = "binance_spot"
    is_buyer_maker: bool = False


class Candle(BaseModel):
    """Aggregated OHLCV candle model."""
    symbol: str
    timeframe: str  # 15m, 1h, 4h
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal = Decimal("0")
    trades_count: int = 0
    is_closed: bool = True


class OrderBookSnapshot(BaseModel):
    """Order book depth snapshot."""
    symbol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bids: List[Tuple[Decimal, Decimal]]  # List of [price, size]
    asks: List[Tuple[Decimal, Decimal]]  # List of [price, size]
    sequence_id: int = 0
