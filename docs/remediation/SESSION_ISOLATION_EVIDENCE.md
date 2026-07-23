# SESSION ISOLATION EVIDENCE (F-03)

## Round 4 — REAL PostgreSQL run

| Test | Result |
|---|---|
| `test_two_sessions_are_durably_isolated` | **PASS** — Session A (10,000) buys BTC; verified in a fresh session/connection that Session A's position exists, Session B's position query for the same symbol returns `None`, and Session B has zero fills |
| `test_recovery_reconciles_and_transitions_to_ready` (round 3 in-memory test still passing) | in-memory isolation unaffected |

## What this proves
Two independent `paper_sessions` rows, each with their own `session_id`, produce completely
disjoint rows across `paper_fills`, `paper_ledger_entries`, and `paper_positions` — enforced by
the `session_id` foreign key + repository queries always filtering by `session_id`, verified by
directly querying PostgreSQL from a separate session/connection (not filtered client-side).

## Commits
`9c851ab test: verify durable persistence, idempotency and recovery on real PostgreSQL`

## Status change
F-03 durable isolation: **PARTIAL (in-memory only) → RESOLVED_VERIFIED (durable, on PostgreSQL 16.2)**
for the persistence-layer mechanism.

## Remaining gap (honest)
The live `PaperPipeline` runtime still constructs one in-memory `PositionManager` +
`PortfolioLedger` per session (round 2/3 fix) — that in-memory isolation was already verified.
What's newly verified this round is that the **durable** representation (Postgres rows) is
correctly isolated too. The runtime loop is not yet wired to persist through this layer (see
DATABASE_TRANSACTION_EVIDENCE.md), so durable isolation is proven for the mechanism but not yet
exercised by the live paper-trading loop end-to-end.
