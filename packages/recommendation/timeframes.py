"""Timeframe-aware freshness bounds.

A candle only closes once per timeframe interval, so "freshness" measured against a flat
wall-clock threshold is meaningless for anything above a 1-minute timeframe: a 4h candle
is, by construction, up to ~4 hours "old" the instant before the next one closes. The
staleness gate must therefore be interval-aware -- a candle is stale if it is older than
its OWN interval plus a grace buffer, not merely older than some fixed number of seconds.
"""

from packages.recommendation.config import RecommendationConfig, recommendation_config

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def max_allowed_staleness_seconds(timeframe: str, config: RecommendationConfig = recommendation_config) -> float:
    interval_seconds = TIMEFRAME_SECONDS.get(timeframe, 0)
    return interval_seconds + float(config.max_market_data_staleness_seconds)
