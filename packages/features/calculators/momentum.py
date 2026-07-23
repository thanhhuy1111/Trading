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

        # Wilder's RSI: seed with a simple average over the first `period` changes,
        # then apply Wilder smoothing over all remaining changes in the history.
        closes = [c.close_price for c in candles]
        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [c if c > Decimal("0") else Decimal("0") for c in changes]
        losses = [-c if c < Decimal("0") else Decimal("0") for c in changes]

        period_dec = Decimal(self.period)
        avg_gain = sum(gains[: self.period], Decimal("0")) / period_dec
        avg_loss = sum(losses[: self.period], Decimal("0")) / period_dec

        for i in range(self.period, len(changes)):
            avg_gain = (avg_gain * (period_dec - Decimal("1")) + gains[i]) / period_dec
            avg_loss = (avg_loss * (period_dec - Decimal("1")) + losses[i]) / period_dec

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
