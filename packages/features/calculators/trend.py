from decimal import Decimal
from typing import List

from packages.features.models import FeatureContext, FeatureDefinition, FeatureValue
from packages.features.registry import feature_registry
from packages.market_data.models import Candle, Timeframe


class SMACalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"sma_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "trend"

    @property
    def required_lookback(self) -> int:
        return self.period

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        period_candles = candles[-self.period:]
        avg = sum((c.close_price for c in period_candles), Decimal("0")) / Decimal(self.period)
        return FeatureValue(name=self.name, version=self.version, value=avg, is_valid=True)


class EMACalculator:
    def __init__(self, period: int = 20, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"ema_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "trend"

    @property
    def required_lookback(self) -> int:
        return self.period

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        # Initial SMA
        initial_candles = candles[-self.required_lookback:]
        ema = sum((c.close_price for c in initial_candles[:self.period]), Decimal("0")) / Decimal(self.period)
        multiplier = Decimal("2") / Decimal(self.period + 1)

        for c in initial_candles[self.period:]:
            ema = (c.close_price - ema) * multiplier + ema

        return FeatureValue(name=self.name, version=self.version, value=ema, is_valid=True)


class EMASlopeCalculator:
    def __init__(self, period: int = 20, slope_period: int = 3, version: str = "1.0.0"):
        self.period = period
        self.slope_period = slope_period
        self._version = version

    @property
    def name(self) -> str:
        return f"ema_{self.period}_slope"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "trend"

    @property
    def required_lookback(self) -> int:
        return self.period + self.slope_period

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        ema_calc = EMACalculator(period=self.period)
        ema_now = ema_calc.calculate(candles, context).value
        ema_prev = ema_calc.calculate(candles[:-self.slope_period], context).value

        if ema_now is None or ema_prev is None or ema_prev == Decimal("0"):
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Calculation error"
            )

        slope = (ema_now - ema_prev) / ema_prev
        return FeatureValue(name=self.name, version=self.version, value=slope, is_valid=True)


class ADXCalculator:
    """Average Directional Index (ADX) Calculator."""
    def __init__(self, period: int = 14, version: str = "1.0.0"):
        self.period = period
        self._version = version

    @property
    def name(self) -> str:
        return f"adx_{self.period}"

    @property
    def version(self) -> str:
        return self._version

    @property
    def category(self) -> str:
        return "trend"

    @property
    def required_lookback(self) -> int:
        return self.period * 2

    def calculate(self, candles: List[Candle], context: FeatureContext) -> FeatureValue:
        if len(candles) < self.required_lookback:
            return FeatureValue(
                name=self.name, version=self.version, value=None, is_valid=False, error_message="Insufficient lookback"
            )

        # Simplified deterministic ADX approximation for MVP
        tr_list = []
        plus_dm_list = []
        minus_dm_list = []

        for i in range(1, len(candles)):
            c_curr = candles[i]
            c_prev = candles[i - 1]
            tr = max(
                c_curr.high_price - c_curr.low_price,
                abs(c_curr.high_price - c_prev.close_price),
                abs(c_curr.low_price - c_prev.close_price)
            )
            tr_list.append(tr)

            up_move = c_curr.high_price - c_prev.high_price
            down_move = c_prev.low_price - c_curr.low_price

            if up_move > down_move and up_move > 0:
                plus_dm_list.append(up_move)
            else:
                plus_dm_list.append(Decimal("0"))

            if down_move > up_move and down_move > 0:
                minus_dm_list.append(down_move)
            else:
                minus_dm_list.append(Decimal("0"))

        avg_tr = sum(tr_list[-self.period:], Decimal("0"))
        avg_plus_dm = sum(plus_dm_list[-self.period:], Decimal("0"))
        avg_minus_dm = sum(minus_dm_list[-self.period:], Decimal("0"))

        if avg_tr == Decimal("0"):
            return FeatureValue(name=self.name, version=self.version, value=Decimal("0"), is_valid=True)

        plus_di = (avg_plus_dm / avg_tr) * Decimal("100")
        minus_di = (avg_minus_dm / avg_tr) * Decimal("100")

        di_sum = plus_di + minus_di
        if di_sum == Decimal("0"):
            dx = Decimal("0")
        else:
            dx = (abs(plus_di - minus_di) / di_sum) * Decimal("100")

        return FeatureValue(name=self.name, version=self.version, value=dx, is_valid=True)


def register_trend_calculators():
    for p in [10, 20, 50]:
        sma = SMACalculator(period=p)
        ema = EMACalculator(period=p)
        ema_slope = EMASlopeCalculator(period=p)

        feature_registry.register(
            FeatureDefinition(
                name=sma.name, version=sma.version, category=sma.category,
                description=f"Simple Moving Average over {p} period(s)", required_lookback=sma.required_lookback,
                supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
                missing_policy="REJECT", warmup_policy="STRICT"
            ),
            sma
        )
        feature_registry.register(
            FeatureDefinition(
                name=ema.name, version=ema.version, category=ema.category,
                description=f"Exponential Moving Average over {p} period(s)", required_lookback=ema.required_lookback,
                supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
                missing_policy="REJECT", warmup_policy="STRICT"
            ),
            ema
        )
        feature_registry.register(
            FeatureDefinition(
                name=ema_slope.name, version=ema_slope.version, category=ema_slope.category,
                description=f"EMA {p} slope over 3 periods", required_lookback=ema_slope.required_lookback,
                supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
                missing_policy="REJECT", warmup_policy="STRICT"
            ),
            ema_slope
        )

    adx = ADXCalculator(period=14)
    feature_registry.register(
        FeatureDefinition(
            name=adx.name, version=adx.version, category=adx.category,
            description="Average Directional Index (ADX 14)", required_lookback=adx.required_lookback,
            supported_timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4], output_type="Decimal",
            missing_policy="REJECT", warmup_policy="STRICT"
        ),
        adx
    )
