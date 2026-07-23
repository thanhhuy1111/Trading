import math
from decimal import Decimal
from typing import List

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.features.registry import feature_registry
from packages.market_data.models import Candle, Timeframe


class RollingZScoreCalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"zscore_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "mean_reversion"

    @property
    def required_lookback(self) -> int:
        return self.period

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        prices = [float(c.close_price) for c in candles[-self.period:]]
        curr_p = prices[-1]

        mean_p = sum(prices) / len(prices)
        variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return FeatureValue(name=self.name, version=self.version, value=Decimal("0"), is_valid=True)

        z = (curr_p - mean_p) / std_dev
        return FeatureValue(name=self.name, version=self.version, value=Decimal(str(z)), is_valid=True)


class BollingerPositionCalculator:
    def __init__(self, period: int = 20, num_std: float = 2.0, version: str = "1.0.0"):
        self.period = period
        self.num_std = num_std
        self._version = version

    @property
    def name(self) -> str:
        return f"bollinger_pos_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "mean_reversion"

    @property
    def required_lookback(self) -> int:
        return self.period

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        prices = [float(c.close_price) for c in candles[-self.period:]]
        curr_p = prices[-1]

        mean_p = sum(prices) / len(prices)
        variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
        std_dev = math.sqrt(variance)

        upper = mean_p + self.num_std * std_dev
        lower = mean_p - self.num_std * std_dev

        if upper == lower:
            return FeatureValue(name=self.name, version=self.version, value=Decimal("0.5"), is_valid=True)

        # %B position: (price - lower) / (upper - lower)
        pct_b = (curr_p - lower) / (upper - lower)
        return FeatureValue(name=self.name, version=self.version, value=Decimal(str(pct_b)), is_valid=True)


def register_reversion_calculators():
    z = RollingZScoreCalculator(period=20)
    feature_registry.register(
        FeatureDefinition(
            name=z.name, version=z.version, category=z.category,
            description="Rolling price Z-score over 20 periods", required_lookback=z.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        z
    )

    bpos = BollingerPositionCalculator(period=20)
    feature_registry.register(
        FeatureDefinition(
            name=bpos.name, version=bpos.version, category=bpos.category,
            description="Bollinger Band %B relative position", required_lookback=bpos.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        bpos
    )
