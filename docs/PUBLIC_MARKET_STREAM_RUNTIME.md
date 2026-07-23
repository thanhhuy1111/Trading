# Public Market Stream Runtime Specification

## 1. Scope & Isolation
The Public Market Stream Runtime (`packages/paper/market_runtime.py`) connects strictly to public, unauthenticated WebSocket and REST endpoints (e.g. Binance public `@kline_1h` streams). No private API endpoints, API keys, or secrets are used or allowed.

---

## 2. Clock Skew Measurement & Audit
- Every incoming public market event carries an `exchange_timestamp`.
- Runtime computes `clock_skew_ms = abs((local_time - exchange_timestamp).total_seconds()) * 1000.0`.
- **Soft Threshold (1,000ms)**: Logs a warning and records connection health metric.
- **Hard Threshold (5,000ms)**: Automatically transitions session status to `DEGRADED` and logs a `CRITICAL_CLOCK_SKEW` incident.

---

## 3. Sequence Validation & Gap Recovery
- Runtime tracks sequential stream message IDs (`sequence_number`).
- If `sequence_number > last_sequence + 1`, a sequence gap is detected.
- Runtime triggers automated REST backfill for missing candles from `last_sequence` to `sequence_number`.
- If REST gap recovery succeeds, stream processing resumes seamlessly. If gap recovery fails after 3 retries, session transitions to `HALTED`.

---

## 4. Data Guardian Validation
All public candles pass through `DataGuardian.validate_ohlc`:
- `high >= max(open, close)`
- `low <= min(open, close)`
- `open, high, low, close > 0`
- Invalid candles are dropped immediately and logged to `paper_connection_incidents`.
