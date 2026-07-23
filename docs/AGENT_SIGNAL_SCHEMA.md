# AgentSignal Schema Specification

```json
{
  "signal_id": "uuid",
  "agent_id": "trend_agent_v1",
  "agent_name": "Trend Following Agent",
  "agent_version": "1.0.0",
  "strategy_type": "TREND_FOLLOWING",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "15m",
  "action": "LONG",
  "expected_return_bps": null,
  "confidence": "0.7500",
  "horizon_minutes": 60,
  "reference_price": "65000.00000000",
  "invalidation_price": "63700.00000000",
  "suggested_stop_price": "63050.00000000",
  "suggested_take_profit_price": "68250.00000000",
  "market_regime": "TREND_UP",
  "feature_snapshot_id": "uuid",
  "feature_set_version": "1.0.0",
  "feature_as_of_time": "2026-07-22T12:00:00Z",
  "generated_at": "2026-07-22T12:00:05Z",
  "expires_at": "2026-07-22T13:00:00Z",
  "reason_codes": ["UPTREND_CONFIRMED", "EMA_SLOPE_POSITIVE"],
  "explanation": ["Evaluated trend alignment for BTC/USDT on 15m timeframe."],
  "quality_flags": [],
  "confidence_type": "HEURISTIC_SCORE",
  "schema_version": 1
}
```

> [!IMPORTANT]
> The schema strictly excludes `quantity`, `notional`, `leverage`, `approved_risk`, `order_type`, and `client_order_id`.
