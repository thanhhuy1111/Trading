from decimal import Decimal
from typing import List

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.features.registry import feature_registry
from packages.market_data.models import Candle, Timeframe


class VolumeSMACalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"volume_sma_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "volume"

    @property
    def required_lookback(self) -> int:
        return self.period

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        period_candles = candles[-self.period:]
        avg_vol = sum((c.volume for c in period_candles), Decimal("0")) / Decimal(self.period)
        return FeatureValue(name=self.name, version=self.version, value=avg_vol, is_valid=True)


class RelativeVolumeCalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"relative_volume_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "volume"

    @property
    def required_lookback(self) -> int:
        return self.period

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        curr_vol = candles[-1].volume
        avg_vol_calc = VolumeSMACalculator(period=self.period)
        avg_vol = avg_vol_calc.calculate(candles, context).value

        if avg_vol is None or avg_vol == Decimal("0"):
            return FeatureValue(name=self.name, version=self.version, value=Decimal("1.0"), is_valid=True)

        rvol = curr_vol / avg_vol
        return FeatureValue(name=self.name, version=self.version, value=rvol, is_valid=True)


def register_volume_calculators():
    vol_sma = VolumeSMACalculator(period=20)
    feature_registry.register(
        FeatureDefinition(
            name=vol_sma.name, version=vol_sma.version, category=vol_sma.category,
            description="Volume Simple Moving Average over 20 periods", required_lookback=vol_sma.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        vol_sma
    )

    rvol = RelativeVolumeCalculator(period=20)
    feature_registry.register(
        FeatureDefinition(
            name=rvol.name, version=rvol.version, category=rvol.category,
            description="Relative Volume ratio compared to 20-period SMA", required_lookback=rvol.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        rvol
    )
