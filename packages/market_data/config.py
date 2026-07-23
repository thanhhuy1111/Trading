from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from packages.market_data.models import Timeframe
from packages.market_data.symbol_registry import symbol_registry


class MarketDataConfig(BaseModel):
    """Typed configuration model for Market Data Platform."""

    provider: str = "binance"
    exchanges: List[str] = Field(default_factory=lambda: ["binance"])
    symbols: List[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    timeframes: List[Timeframe] = Field(
        default_factory=lambda: [
            Timeframe.M1,
            Timeframe.M5,
            Timeframe.M15,
            Timeframe.H1,
            Timeframe.H4,
        ]
    )
    historical_start: Optional[datetime] = None
    websocket_enabled: bool = True
    order_book_enabled: bool = True
    order_book_depth: int = 100
    candle_storage_enabled: bool = True
    trade_storage_enabled: bool = True
    stale_threshold_seconds: Dict[str, int] = Field(
        default_factory=lambda: {"trades": 30, "candles": 120, "order_book": 10}
    )
    reconnect_initial_delay_seconds: Decimal = Decimal("1.0")
    reconnect_max_delay_seconds: Decimal = Decimal("10.0")
    max_reconnect_attempts: int = 5
    rate_limit_safety_ratio: Decimal = Decimal("0.8")

    @model_validator(mode="after")
    def validate_market_config(self):
        # Validate symbols
        for sym in self.symbols:
            if not symbol_registry.get_symbol_info(sym):
                raise ValueError(f"Unknown symbol '{sym}' in MarketDataConfig")
        # Validate thresholds
        if self.order_book_depth <= 0 or self.order_book_depth > 1000:
            raise ValueError("order_book_depth must be between 1 and 1000")
        if not (Decimal("0") <= self.rate_limit_safety_ratio <= Decimal("1")):
            raise ValueError("rate_limit_safety_ratio must be between 0.0 and 1.0")
        return self
