from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict

from pydantic import BaseModel, Field


class FeatureSnapshot(BaseModel):
    """Calculated technical indicator and market feature snapshot."""
    symbol: str
    timeframe: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    close_price: Decimal
    returns_1p: float = 0.0
    volatility_20p: float = 0.0
    atr_14: float = 0.0
    adx_14: float = 0.0
    ema_20: float = 0.0
    ema_50: float = 0.0
    ema_200: float = 0.0
    rsi_14: float = 0.0
    z_score_20: float = 0.0
    vwap_deviation: float = 0.0
    volume_sma_20: float = 0.0
    bid_ask_spread_bps: float = 0.0
    custom_metrics: Dict[str, Any] = Field(default_factory=dict)
