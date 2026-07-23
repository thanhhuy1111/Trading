# Shadow Mode (Phase 10)

`packages/shadow/{builder,service}.py`. Never places a real order - `evaluate_due()` only ever
reads historical/point-in-time candles through an injected provider and writes a
`ShadowOutcome` record; there is no execution client import anywhere in this module.

## Building a snapshot - `packages/shadow/builder.py`

`build_shadow_proposal(proposal, market_data_timestamp, ...)` constructs the immutable
`ShadowProposal` entity (`model_config = {"frozen": True}`, Phase 1) from a `TradeProposal`
plus whatever upstream-stage snapshots the caller has in hand (feature/regime/agent/meta-label/
market-context/evidence/ranking/correlation/portfolio-risk - every one defaults to an honest
empty `{}`/`[]` rather than being required). Computes and stamps the checksum.

`shadow_kind_for_application_result_state(state)` maps `APPROVED_PROPOSAL` ->
`APPROVED_SHADOW`, `RESEARCH_PROPOSAL` -> `RESEARCH_SHADOW`, and returns `None` for every other
`ApplicationResultState` - those states never produce a `TradeProposal` to shadow in the first
place, so `build_shadow_proposal` raises `ValueError` if called with one.

## Storage and tamper detection - `packages/shadow/service.py`

`InMemoryShadowStore` - offline, in-process (designed like `EvidenceAuditLog` to drain into a
durable, append-only table later). `BaselineShadowService.record_proposal()` recomputes the
snapshot's own checksum and compares it against any caller-supplied one, raising
`ShadowProposalTamperedError` on mismatch rather than trusting a manually-crafted object.

## Outcome evaluation

`schedule_evaluation(shadow_id, due_at)` creates a `PENDING` `ShadowOutcome`.
`evaluate_due(as_of_time)` scans due, still-`PENDING` outcomes and, for each:

1. Reads the candidate's `symbol`/`timeframe`/`direction`/`entry_reference`/`stop_loss`/
   `take_profit` from the frozen `candidate_snapshot` dict.
2. Walks real candles between `market_data_timestamp` and the due time.
3. First stop-loss/take-profit touch wins -> `BARRIER_EXIT` (`barrier_hit` = `"UPPER"` or
   `"LOWER"`).
4. No barrier configured or touched -> mark-to-last-close at the due time -> `TIMEOUT_EXIT`.
5. No candles at all in the window -> `DATA_UNAVAILABLE` - never a fabricated result.

Direction is LONG-only, matching this architecture's spot-only MVP everywhere else.

## Cost model

`total_cost_bps = 2 * (estimated_fee_bps + estimated_spread_bps + estimated_slippage_bps)` -
entry and exit each pay once. This is a documented simplification, not a claim about realized
execution cost (Master Plan: "do not optimize toward profitable backtest results in this
task").

## Calibration aggregation

`aggregate_calibration(proposals, outcomes_by_shadow_id, bucket_width=0.1)` buckets resolved
outcomes (`BARRIER_EXIT`/`TIMEOUT_EXIT` only) by the proposal's `calibrated_probability` into
decile buckets and reports realized win rate (`net_return_bps > 0`) per bucket. Unresolved
outcomes (`PENDING`/`DATA_UNAVAILABLE`) and proposals with no probability are excluded, never
counted as a 0%/100% win. This is the calibration-curve input Phase 11 monitoring and Phase 12
retraining evidence review consume.

## `APPROVED_SHADOW` vs `RESEARCH_SHADOW`

Both kinds go through the identical storage/evaluation code path - the only difference is
`kind`, set once at build time from the originating `TradeProposal`'s
`application_result_state`. Nothing in `evaluate_due()` branches on `kind` at all, so an
approved-shadow's outcome evaluation can never accidentally diverge from a research-shadow's.
