# Market Data Platform Runbook

## 1. Triggering Historical Candle Ingestion
Use the REST API to trigger a historical ingestion job:

```bash
curl -X POST http://localhost:8000/market-data/ingestion-jobs \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "binance",
    "symbol": "BTC/USDT",
    "timeframe": "1m",
    "start_time": "2026-07-22T00:00:00Z",
    "end_time": "2026-07-22T12:00:00Z"
  }'
```

## 2. Triggering Market Data State Resync
To resync order book snapshots or clear stream sequence gaps (read-only state refresh; zero trading impact):

```bash
curl -X POST http://localhost:8000/data-quality/resync/BTC/USDT
```
