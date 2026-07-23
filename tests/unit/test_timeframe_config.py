"""1h and 4h must have their own config, never 1D's borrowed values."""

import pytest

from packages.backtest.timeframe_config import TIMEFRAME_CONFIGS, get_timeframe_config
from packages.market_data.models import Timeframe


def test_all_three_research_timeframes_are_configured() -> None:
    for tf in (Timeframe.D1, Timeframe.H4, Timeframe.H1):
        cfg = get_timeframe_config(tf)
        assert cfg.timeframe == tf


def test_configs_are_not_identical_across_timeframes() -> None:
    d1 = get_timeframe_config(Timeframe.D1)
    h4 = get_timeframe_config(Timeframe.H4)
    h1 = get_timeframe_config(Timeframe.H1)

    assert d1.label_horizon != h4.label_horizon != h1.label_horizon
    assert d1.upper_barrier_pct != h4.upper_barrier_pct != h1.upper_barrier_pct
    assert d1.lower_barrier_pct != h4.lower_barrier_pct != h1.lower_barrier_pct
    assert d1.purge_period != h4.purge_period != h1.purge_period
    assert d1.minimum_trade_count != h4.minimum_trade_count != h1.minimum_trade_count
    assert d1.proposal_expiry != h4.proposal_expiry != h1.proposal_expiry


def test_unconfigured_timeframe_raises_not_falls_back() -> None:
    with pytest.raises(KeyError):
        get_timeframe_config(Timeframe.M15)


def test_purge_and_embargo_match_label_horizon() -> None:
    for tf in (Timeframe.D1, Timeframe.H4, Timeframe.H1):
        cfg = get_timeframe_config(tf)
        assert cfg.purge_period == cfg.label_horizon
        assert cfg.embargo_period == cfg.label_horizon


def test_higher_frequency_timeframes_require_more_trades() -> None:
    d1 = get_timeframe_config(Timeframe.D1)
    h4 = get_timeframe_config(Timeframe.H4)
    h1 = get_timeframe_config(Timeframe.H1)
    assert h1.minimum_trade_count > h4.minimum_trade_count > d1.minimum_trade_count


def test_registry_is_exhaustive_and_keyed_correctly() -> None:
    for tf, cfg in TIMEFRAME_CONFIGS.items():
        assert cfg.timeframe == tf
