# Data Quality Policy & Data Guardian Specification

## 1. Quality Dimensions
1. **Freshness**: Trade, candle, and order-book streams must emit messages within configurable stale thresholds (e.g. 30s for trades, 120s for candles).
2. **Completeness**: Detects sequence gaps, missing candles, and incomplete warm-up data.
3. **Validity**: Enforces $Price > 0$, $Quantity > 0$, valid OHLC relations ($High \ge \max(Open, Close, Low)$), and uncrossed order books ($BestBid < BestAsk$).
4. **Consistency**: Verifies REST snapshot vs WebSocket stream price alignment.
5. **Anomaly Detection**: Identifies price jumps, volume spikes, and crossed book levels.

## 2. Status Hierarchy & Recommended Actions
- `HEALTHY`: `CONTINUE`
- `DEGRADED`: `DEGRADE_FEATURES` / `RESYNC`
- `UNHEALTHY`: `PAUSE_SYMBOL` / `CREATE_INCIDENT`
- `STALE`: `RESYNC`
- `RESYNCING`: `RESYNC`
