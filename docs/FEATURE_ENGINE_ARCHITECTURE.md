# Feature Engine Architecture Specification

## 1. Overview
The Feature Engine computes technical indicators and feature vectors from closed candles (`15m`, `1h`, `4h`), enforcing strict zero lookahead leakage temporal invariants:

```
Closed Candle (T) -> Data Quality Gate -> Feature Calculator -> Feature Validator -> Feature Store -> AgentRunner
```

- **Temporal Invariant**: `lookback_end <= as_of_time` and `event_time <= as_of_time`.
- **Zero Leakage**: Features calculated at timestamp $T$ yield 100% identical outputs regardless of whether future candles ($T+1 \dots T+N$) exist.

## 2. Feature Storage
- **Minimal Profile**: PostgreSQL `feature_definitions`, `feature_sets`, and `feature_snapshots` tables.
- **Full Profile**: ClickHouse historical feature persistence (pending live verification).
