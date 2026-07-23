# RISK WINDOW EVIDENCE (F-05, F-13)

| Finding | Implementation | Unit evidence | Integration evidence | Runtime evidence | Status |
|---|---|---|---|---|---|
| F-05 | UTC-day / ISO-week realized-PnL buckets keyed by committed fill `event_time` | `tests/unit/test_risk_pnl_windows.py` (5 tests) | NONE (logic needs no DB) | Unit-level | **RESOLVED_VERIFIED** (in-memory; durable bucket persistence is F-04, OPEN) |
| F-13 | `RiskGovernor` resolves `current_time = eval_time` before any comparison | governor tests green | — | — | **RESOLVED_VERIFIED** |

## Verified
- Yesterday's realized loss is NOT counted in today's daily bucket; it remains in the same ISO-week bucket.
- Weekly bucket resets on the next ISO week.
- A late fill (processed later, `event_time` in a past day) books PnL to the correct past bucket, not the processing day.
- Bucketing is by **UTC** regardless of the event's timezone (an event at 23:30 UTC-2 books to the 24th UTC day).
- Two managers have independent buckets.
- Risk snapshot (`realized_pnl_today` / `realized_pnl_week`) now reads the current window by injected `current_time`, feeding the state machine's daily/weekly kill-switch checks correctly.

## Notes
- Evaluation time is injected via `current_time` on `get_portfolio_snapshot` / `get_risk_governor_snapshot` / `evaluate_intent` — no wall-clock calls in the bucket selection or governor comparison paths.
- Bucket state is in-memory this pass; persisting `realized_pnl_buckets` (so limits survive restart) is part of F-04 and is BLOCKED (no Postgres).
