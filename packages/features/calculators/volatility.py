import math
from decimal import Decimal
from typing import List

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.features.registry import feature_registry
from packages.market_data.models import Candle, Timeframe


class ATRCalculator:
    def __init__(self, period: int = 14, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"atr_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "volatility"

    @property
    def required_lookback(self) -> int:
        return self.period + 1

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        tr_sum = Decimal("0")
        period_candles = candles[-(self.period + 1):]

        for i in range(1, len(period_candles)):
            c_curr = period_candles[i]
            c_prev = period_candles[i - 1]
            tr = max(
                c_curr.high_price - c_curr.low_price,
                abs(c_curr.high_price - c_prev.close_price),
                abs(c_curr.low_price - c_prev.close_price)
            )
            tr_sum += tr

        atr = tr_sum / Decimal(self.period)
        return FeatureValue(name=self.name, version=self.version, value=atr, is_valid=True)


class RealizedVolatilityCalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"volatility_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "volatility"

    @property
    def required_lookback(self) -> int:
        return self.period + 1

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        returns = []
        period_candles = candles[-(self.period + 1):]

        for i in range(1, len(period_candles)):
            p_prev = float(period_candles[i - 1].close_price)
            p_curr = float(period_candles[i].close_price)
            if p_prev > 0:
                ret = math.log(p_curr / p_prev)
                returns.append(ret)

        if not returns:
            return FeatureValue(name=self.name, version=self.version, value=Decimal("0"), is_valid=True)

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        return FeatureValue(name=self.name, version=self.version, value=Decimal(str(std_dev)), is_valid=True)


def register_volatility_calculators():
    atr = ATRCalculator(period=14)
    feature_registry.register(
        FeatureDefinition(
            name=atr.name, version=atr.version, category=atr.category,
            description="Average True Range (ATR 14)", required_lookback=atr.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        atr
    )

    vol = RealizedVolatilityCalculator(period=20)
    feature_registry.register(
        FeatureDefinition(
            name=vol.name, version=vol.version, category=vol.category,
            description="Realized Volatility over 20 periods", required_lookback=vol.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        vol
    )
