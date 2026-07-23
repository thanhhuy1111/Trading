# Market Data Architecture Specification

## 1. Overview
The Market Data Platform collects, normalizes, validates, and persists public cryptocurrency market data for Spot trading symbols (`BTC/USDT`, `ETH/USDT`) across supported timeframes (`1m`, `5m`, `15m`, `1h`, `4h`).

```
+--------------------------+     +--------------------------+     +--------------------------+
| Public Binance Exchange  | --> | MarketDataProvider       | --> | SymbolRegistry           |
| (REST & WebSockets)      |     | (BinancePublicAdapter)   |     | (BTC/USDT <-> BTCUSDT)   |
+--------------------------+     +--------------------------+     +--------------------------+
                                              |
                                              v
+--------------------------+     +--------------------------+     +--------------------------+
| Data Guardian            | <-- | LocalOrderBookService    | <-- | CandleLifecycleManager   |
| (Quality & Anomalies)    |     | (Snapshot + WS Deltas)   |     | (Closed Candle Events)   |
+--------------------------+     +--------------------------+     +--------------------------+
             |                                                                 |
             v                                                                 v
+--------------------------+                                     +--------------------------+
| DataQualityChanged Event |                                     | Transactional Outbox     |
| (market.data_quality_...)|                                     | & PostgreSQL Storage     |
+--------------------------+                                     +--------------------------+
```

## 2. Safety Rules
- Uses public REST and WebSocket market data endpoints ONLY.
- No trading API keys or private user data streams required.
- Contains ZERO order execution code or order placement methods.
- Live trading remains strictly disabled.
