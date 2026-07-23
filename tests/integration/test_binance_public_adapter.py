import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from packages.market_data.adapters.binance import BinancePublicMarketDataProvider
from packages.market_data.models import Timeframe


def test_binance_public_fetch_candles():
    """Integration Test: Fetches public historical candles from Binance for BTC/USDT and ETH/USDT."""
    async def _test():
        provider = BinancePublicMarketDataProvider()
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=10)

        # Test BTC/USDT
        btc_candles = await provider.fetch_candles("BTC/USDT", Timeframe.M1, start_time, end_time, limit=5)
        assert len(btc_candles) > 0
        assert btc_candles[0].symbol == "BTC/USDT"
        assert isinstance(btc_candles[0].close_price, Decimal)
        assert btc_candles[0].open_time.tzinfo is not None

        # Test ETH/USDT
        eth_candles = await provider.fetch_candles("ETH/USDT", Timeframe.M1, start_time, end_time, limit=5)
        assert len(eth_candles) > 0
        assert eth_candles[0].symbol == "ETH/USDT"
        assert isinstance(eth_candles[0].close_price, Decimal)

    asyncio.run(_test())


def test_binance_public_fetch_order_book_snapshot():
    """Integration Test: Fetches public order book snapshot from Binance for BTC/USDT."""
    async def _test():
        provider = BinancePublicMarketDataProvider()
        snapshot = await provider.fetch_order_book_snapshot("BTC/USDT", depth=5)
        assert snapshot.symbol == "BTC/USDT"
        assert snapshot.sequence_id > 0
        assert len(snapshot.bids) > 0
        assert len(snapshot.asks) > 0
        assert snapshot.bids[0].price < snapshot.asks[0].price

    asyncio.run(_test())
