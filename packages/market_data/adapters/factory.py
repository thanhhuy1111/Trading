from packages.market_data.adapters.base import MarketDataProvider
from packages.market_data.adapters.binance import BinancePublicMarketDataProvider
from packages.market_data.adapters.mock import MockMarketDataProvider
from packages.market_data.adapters.replay import ReplayMarketDataProvider


class MarketDataProviderFactory:
    """Factory selecting MarketDataProvider based on configuration."""

    @staticmethod
    def create_provider(provider_type: str = "binance", **kwargs) -> MarketDataProvider:
        pt = provider_type.lower()
        if pt == "binance":
            return BinancePublicMarketDataProvider(**kwargs)
        elif pt == "mock":
            return MockMarketDataProvider(**kwargs)
        elif pt == "replay":
            return ReplayMarketDataProvider(**kwargs)
        else:
            raise ValueError(f"Unsupported market data provider type: '{provider_type}'")
