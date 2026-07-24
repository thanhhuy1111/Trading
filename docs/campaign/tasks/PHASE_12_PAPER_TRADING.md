# Phase 12 — Paper Trading

Status: **COMPLETE**

## Scope and architecture

- Reused the existing public-data-only paper pipeline, deterministic risk governor,
  session-scoped ledger, long-only position manager and exit protector.
- Kept position sizing under the code-only risk governor. SHORT remains unsupported until a
  separate risk/accounting contract and tests exist.
- Made paper order/fill identifiers and execution timestamps deterministic from the immutable
  order request. Fee remains 10 bps and slippage 5 bps, with entry/exit limit protection.
- Fixed fill idempotency across both ledger and position state. A duplicate fill can no longer
  change cash, quantity, PnL or history; a balance-rejected fill remains retryable.
- Added immutable equity points, trade records and portfolio reports covering cash, NAV,
  return, fees, realized/unrealized PnL, drawdown, win rate and open positions.
- Added migration 014 and deterministic durable IDs; persisted protection/valuation state is
  replayed into fees, history and PnL buckets on recovery. Recovery fails closed when an open
  position has no persisted stop/take-profit.
- Terminal filled orders cannot be relabeled cancelled.

No network adapter, private exchange API, live order endpoint or mode-transition mechanism was
added.

## Acceptance evidence

- Focused paper/position/durability tests: 41 passed, 12 skipped.
- Full suite: 589 passed, 12 skipped, 1 known Alembic failure.
- Ruff on paper/position code and Phase 12 tests: clean.
- Targeted mypy exposes three existing baseline errors in shared logger/risk snapshot code;
  Phase 12 reporting and adapter add no new reported error.
- Repeat reporting at an identical event time is equal.
- Regression tests cover duplicate/conflicting order processing, deterministic clean replay,
  terminal cancellation, atomic SELL rejection, negative-cash rejection/retry, lifetime fees,
  approved stop/take-profit, point-in-time reports, approval bounds and drawdown.
- Gap-through-stop updates valuation, records an unresolved protective exit and HALTs the
  session instead of hiding loss or fabricating an out-of-envelope fill.

Synthetic fixtures validate contracts only. They are not market-performance evidence.
The 12 PostgreSQL drills remain skipped because `PAPER_DB_TEST_URL` is not configured; the
new migration and durable recovery path are therefore implemented but not database-verified.

## Safety status

- Paper execution remains `ExecutionMode.PAPER`.
- Long/Hold only; no short path.
- No private credentials or exchange calls.
- Live/private feature defaults remain false.
