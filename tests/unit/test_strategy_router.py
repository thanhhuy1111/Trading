"""Strategy Router must be deterministic, versioned, and must NO_TRADE on LOW_LIQUIDITY /
UNKNOWN / TRANSITION regimes."""

from packages.agents.models import MarketRegime, StrategyType
from packages.governance.strategy_router import ROUTER_VERSION, route


def test_every_market_regime_has_a_routing_entry() -> None:
    for regime in MarketRegime:
        decision = route(regime)
        assert decision.regime == regime
        assert decision.router_version == ROUTER_VERSION


def test_trend_up_routes_to_trend_following() -> None:
    decision = route(MarketRegime.TREND_UP)
    assert decision.allowed_strategy_types == frozenset({StrategyType.TREND_FOLLOWING})
    assert decision.is_no_trade is False


def test_sideways_routes_to_mean_reversion() -> None:
    decision = route(MarketRegime.SIDEWAYS)
    assert decision.allowed_strategy_types == frozenset({StrategyType.MEAN_REVERSION})


def test_high_volatility_routes_to_breakout() -> None:
    decision = route(MarketRegime.HIGH_VOLATILITY)
    assert decision.allowed_strategy_types == frozenset({StrategyType.BREAKOUT})


def test_low_liquidity_never_routes_a_strategy() -> None:
    decision = route(MarketRegime.LIQUIDITY_RISK)
    assert decision.allowed_strategy_types == frozenset()
    assert decision.is_no_trade is True
    assert "REGIME_LOW_LIQUIDITY_NO_TRADE" in decision.reason_codes


def test_unknown_and_transition_regimes_are_no_trade() -> None:
    for regime in (MarketRegime.UNKNOWN, MarketRegime.TRANSITION):
        decision = route(regime)
        assert decision.is_no_trade is True
        assert decision.allowed_strategy_types == frozenset()


def test_routing_is_deterministic() -> None:
    a = route(MarketRegime.TREND_UP)
    b = route(MarketRegime.TREND_UP)
    assert a == b
