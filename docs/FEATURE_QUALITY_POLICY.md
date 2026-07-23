# Feature Quality Policy & Validation Rules

## 1. Quality Statuses
- `VALID`: All computed features present, numeric, and strictly within expected ranges.
- `DEGRADED`: Minor missing values or non-critical warnings. Agent confidence penalized.
- `INVALID`: Contains NaN, Infinity, or out-of-range violations (e.g. RSI outside 0..100). Agents REJECT snapshot.
- `WARMING_UP`: Insufficient lookback candles available.

## 2. Validation Checks
1. **Numeric Integrity**: Rejects NaN, Infinity, and floating-point overflow.
2. **Range Validation**: RSI $[0, 100]$, ADX $\ge 0$, ATR $\ge 0$, Volume $\ge 0$.
3. **Temporal Invariants**: Enforces `lookback_end <= as_of_time` and `event_time <= as_of_time`.
