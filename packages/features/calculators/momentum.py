from decimal import Decimal
from typing import List

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.features.registry import feature_registry
from packages.market_data.models import Candle, Timeframe


class RSICalculator:
    def __init__(self, period: int = 14, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"rsi_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "momentum"

    @property
    def required_lookback(self) -> int:
        return self.period + 1

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        gains = Decimal("0")
        losses = Decimal("0")

        period_candles = candles[-(self.period + 1):]
        for i in range(1, len(period_candles)):
            change = period_candles[i].close_price - period_candles[i - 1].close_price
            if change > 0:
                gains += change
            else:
                losses += abs(change)

        avg_gain = gains / Decimal(self.period)
        avg_loss = losses / Decimal(self.period)

        if avg_loss == Decimal("0"):
            rsi = Decimal("100.00")
        else:
            rs = avg_gain / avg_loss
            rsi = Decimal("100.00") - (Decimal("100.00") / (Decimal("1.00") + rs))

        # Clamp RSI to [0, 100]
        rsi = max(Decimal("0.00"), min(Decimal("100.00"), rsi))
        return FeatureValue(name=self.name, version=self.version, value=rsi, is_valid=True)


def register_momentum_calculators():
    rsi = RSICalculator(period=14)
    feature_registry.register(
        FeatureDefinition(
            name=rsi.name, version=rsi.version, category=rsi.category,
            description="Relative Strength Index (RSI 14)", required_lookback=rsi.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        rsi
    )
