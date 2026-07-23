# Exchange Adapter Specification

## 1. Abstract Provider Protocol (`MarketDataProvider`)
All business components depend strictly on the `MarketDataProvider` protocol:

- `get_exchange_info()`: Fetches rate limits and timeframe capabilities.
- `get_symbol_info(symbol)`: Retrieves normalized symbol metadata.
- `fetch_candles(symbol, timeframe, start_time, end_time, limit)`: Historical kline downloader.
- `fetch_order_book_snapshot(symbol, depth)`: Order book snapshot fetcher.
- `stream_trades(symbols)`: Async trade stream generator.
- `stream_candles(symbols, timeframes)`: Async candle update generator.
- `stream_order_book(symbols)`: Async order book delta stream generator.

## 2. Implementations
1. `BinancePublicMarketDataProvider`: Real read-only public REST and WebSocket adapter (`https://api.binance.com`).
2. `MockMarketDataProvider`: Mock provider for fast local unit testing without network calls.
3. `ReplayMarketDataProvider`: Historical candle replay provider for backtesting simulations.
