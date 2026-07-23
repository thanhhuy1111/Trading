# Known Limitations & Scope Boundaries

## Scope Boundaries
1. **Live Trading**: System is strictly designed for **Paper Trading** and **Historical Simulation**. Real-money order execution is disabled by design.
2. **Private Exchange APIs**: Exchange account credentials, withdrawals, deposits, margin, futures, leverage, and short selling are NOT supported.
3. **Market Streams**: System consumes public ticker and candle streams only (`wss://stream.binance.com`).

## Technical Debt & Maintenance Guidelines
- ClickHouse feature store and Redpanda event bus drivers remain pending full production cluster deployment verification.
- System operates cleanly on PostgreSQL and local message bus memory profiles.
