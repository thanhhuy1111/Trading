from decimal import Decimal
from typing import List

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.features.registry import feature_registry
from packages.market_data.models import Candle, Timeframe


class SimpleReturnCalculator:
    def __init__(self, period: int = 1, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"return_{self.period}p"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "price_return"

    @property
    def required_lookback(self) -> int:
        return self.period + 1

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        p_current = candles[-1].close_price
        p_prev = candles[-(self.period + 1)].close_price

        if p_prev == Decimal("0"):
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Zero price division"
            )

        ret = (p_current - p_prev) / p_prev
        return FeatureValue(name=self.name, version=self.version, value=ret, is_valid=True)


class HighLowRangeCalculator:
    def __init__(self, version: str = "1.0.0"):
        self._version = version

    @property
    def name(self) -> str:
        return "high_low_range"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "price_return"

    @property
    def required_lookback(self) -> int:
        return 1

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if not candles:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Empty candles"
            )

        c = candles[-1]
        if c.low_price == Decimal("0"):
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Zero low price"
            )

        hl_ratio = (c.high_price - c.low_price) / c.low_price
        return FeatureValue(name=self.name, version=self.version, value=hl_ratio, is_valid=True)


def register_returns_calculators():
    for p in [1, 3, 5, 10, 20]:
        calc = SimpleReturnCalculator(period=p)
        defn = FeatureDefinition(
            name=calc.name,
            version=calc.version,
            category=calc.category,
            description=f"Simple percentage return over {p} period(s)",
            required_lookback=calc.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4],
            output_type="Decimal",
            missing_policy="REJECT",
            warmup_policy="STRICT"
        )
        feature_registry.register(defn, calc)

    hl_calc = HighLowRangeCalculator()
    hl_defn = FeatureDefinition(
        name=hl_calc.name,
        version=hl_calc.version,
        category=hl_calc.category,
        description="High to Low relative price range",
        required_lookback=hl_calc.required_lookback,
        supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4],
        output_type="Decimal",
        missing_policy="REJECT",
        warmup_policy="STRICT"
    )
    feature_registry.register(hl_defn, hl_calc)
