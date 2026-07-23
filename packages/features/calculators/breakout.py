from decimal import Decimal
from typing import List

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.features.registry import feature_registry
from packages.market_data.models import Candle, Timeframe


class DonchianBreakoutCalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"donchian_breakout_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "breakout"

    @property
    def required_lookback(self) -> int:
        return self.period + 1

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        curr_candle = candles[-1]
        lookback_candles = candles[-(self.period + 1):-1]

        max_high = max(c.high_price for c in lookback_candles)
        min_low = min(c.low_price for c in lookback_candles)

        if curr_candle.close_price > max_high:
            signal = Decimal("1.0")  # Bullish breakout
        elif curr_candle.close_price < min_low:
            signal = Decimal("-1.0")  # Bearish breakout
        else:
            signal = Decimal("0.0")  # Inside range

        return FeatureValue(name=self.name, version=self.version, value=signal, is_valid=True)


def register_breakout_calculators():
    db = DonchianBreakoutCalculator(period=20)
    feature_registry.register(
        FeatureDefinition(
            name=db.name, version=db.version, category=db.category,
            description="Donchian Channel Breakout signal (+1 bullish, -1 bearish, 0 inside)",
            required_lookback=db.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        db
    )
