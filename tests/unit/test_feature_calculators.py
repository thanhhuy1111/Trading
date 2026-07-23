from datetime import datetime, timezone
from decimal import Decimal

from packages.features.calculators.momentum import RSICalculator
from packages.features.calculators.returns import SimpleReturnCalculator
from packages.features.calculators.trend import SMACalculator
from packages.features.models import FeatureContext
from packages.market_data.models import Candle, Timeframe


def make_candle(close_p: str, i: int) -> Candle:
    now = datetime.now(timezone.utc)
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe=Timeframe.M15,
        open_time=now,
        close_time=now,
        open_price=Decimal(close_p),
        high_price=Decimal(close_p) + Decimal("1.0"),
        low_price=Decimal(close_p) - Decimal("1.0"),
        close_price=Decimal(close_p),
        volume=Decimal("100.0"),
        exchange_timestamp=now
    )


def test_simple_return_calculator():
    candles = [make_candle("100.0", 1), make_candle("110.0", 2)]
    ctx = FeatureContext(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.M15,
        as_of_time=datetime.now(timezone.utc), data_quality_status="HEALTHY"
    )
    calc = SimpleReturnCalculator(period=1)
    res = calc.calculate(candles, ctx)
    assert res.is_valid is True
    assert res.value == Decimal("0.1")


def test_sma_calculator():
    candles = [make_candle(str(10 + i), i) for i in range(10)]
    ctx = FeatureContext(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.M15,
        as_of_time=datetime.now(timezone.utc), data_quality_status="HEALTHY"
    )
    calc = SMACalculator(period=5)
    res = calc.calculate(candles, ctx)
    assert res.is_valid is True
    assert res.value == Decimal("17.0")  # (15+16+17+18+19)/5 = 17


def test_rsi_calculator_bounded():
    candles = [make_candle(str(100 + i * 2), i) for i in range(20)]
    ctx = FeatureContext(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.M15,
        as_of_time=datetime.now(timezone.utc), data_quality_status="HEALTHY"
    )
    calc = RSICalculator(period=14)
    res = calc.calculate(candles, ctx)
    assert res.is_valid is True
    assert Decimal("0.0") <= res.value <= Decimal("100.0")
