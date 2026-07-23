# Backtest Fill Assumptions & Realistic Modeling

## 1. Execution Chronology
Orders submitted after candle $T$ close are executed at candle $T+1$ open price with configurable slippage (default 5 bps) and exchange fee (default 10 bps taker fee).

## 2. Invariants
- `NO_SAME_BAR_FILL` default prevents optimistic entry fill at $T$ close price.
- Fills cannot exceed approved risk quantity.
