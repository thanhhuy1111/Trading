# MIGRATION EVIDENCE

**No database migrations were added or changed in this pass.**

The durable-persistence work (F-04: persist sessions/orders/fills/ledger/positions with
unique constraints on `fill_id`, `client_order_id`, `(session_id, symbol, timeframe,
candle_close_time)`, `decision_id`) is NOT_STARTED, so no new Alembic revision exists yet.

The migration cycle was therefore not exercised:

| Command | Status | Reason |
|---|---|---|
| `alembic upgrade head` | NOT RUN | `alembic` not installed in this environment; no disposable Postgres available |
| `alembic downgrade -1` | NOT RUN | same |
| `alembic upgrade head` | NOT RUN | same |

Existing migrations `001`–`012` are unchanged. When F-04 is implemented, a new additive
migration (e.g. `013_paper_runtime_persistence.py`) with matching `downgrade()` and an
upgrade/downgrade/upgrade cycle test must be added and run on a disposable database.
