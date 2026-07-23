"""DecisionService.decide's allowed_strategy_types param must actually gate which agents run,
and default to unchanged (all-agents) behavior when omitted."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.agents.models import StrategyType
from packages.governance.decision_service import decision_service
from packages.market_data.models import Candle, Timeframe

T0 = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _candles(n: int = 40) -> list:
    candles = []
    price = Decimal("50000")
    for i in range(n):
        ct = T0 + timedelta(hours=i)
        step = price * Decimal("0.005")
        candles.append(Candle(
            exchange="binance", symbol="BTC/USDT", exchange_timestamp=ct, open_time=ct,
            close_time=ct + timedelta(minutes=59), timeframe=Timeframe.H1, open_price=price,
            high_price=price + step + Decimal("10"), low_price=price - Decimal("10"),
            close_price=price + step, volume=Decimal("100"), trades_count=100, is_closed=True,
        ))
        price += step
    return candles


async def _decide(candles, allowed=None):
    last = candles[-1]
    return await decision_service.decide(
        exchange="binance", symbol="BTC/USDT", timeframe=Timeframe.H1,
        candles=candles, as_of_time=last.close_time, reference_price=last.close_price,
        allowed_strategy_types=allowed,
    )


async def test_default_none_runs_all_three_agents() -> None:
    result = await _decide(_candles())
    assert len(result.signals) == 3


async def test_empty_allowed_set_runs_zero_agents_and_forces_no_trade() -> None:
    result = await _decide(_candles(), allowed=frozenset())
    assert result.signals == []
    assert result.trade_intent is None
    assert result.allocation.result.value == "NO_TRADE"


async def test_single_strategy_type_runs_only_that_agent() -> None:
    result = await _decide(_candles(), allowed=frozenset({StrategyType.TREND_FOLLOWING}))
    assert len(result.signals) == 1
    assert result.signals[0].strategy_type == StrategyType.TREND_FOLLOWING


async def test_two_strategy_types_run_exactly_those_two() -> None:
    allowed = frozenset({StrategyType.MEAN_REVERSION, StrategyType.BREAKOUT})
    result = await _decide(_candles(), allowed=allowed)
    assert len(result.signals) == 2
    assert {s.strategy_type for s in result.signals} == allowed
