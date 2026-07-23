from packages.market_data.adapters.binance import BinancePublicMarketDataProvider
from packages.market_data.adapters.mock import MockMarketDataProvider
from packages.market_data.adapters.replay import ReplayMarketDataProvider


def test_market_data_adapters_have_no_order_execution_methods():
    """Safety Test: Proves that exchange market data providers contain NO order placement or private API methods."""
    prohibited_substrings = ["create_order", "place_order", "cancel_order", "submit_order", "buy", "sell", "private"]

    for provider_cls in [BinancePublicMarketDataProvider, MockMarketDataProvider, ReplayMarketDataProvider]:
        method_names = [m for m in dir(provider_cls) if not m.startswith("__")]
        for m in method_names:
            for prohibited in prohibited_substrings:
                msg = f"Safety Violation: Provider '{provider_cls.__name__}' contains method '{m}'"
                assert prohibited not in m.lower(), msg
