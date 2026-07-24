# Phase 10 — API & Dashboard

## Status

**COMPLETE**

## Delivered

- Exact `/api/v1` market, analysis, prediction and system-health route set.
- Public-data deterministic research trigger for registered BTC/USDT and ETH/USDT timeframes.
  It consumes only closed Binance public candles, computes the existing point-in-time feature
  set, classifies regime, routes the rule agent, runs critic/consensus/allocation and emits
  source-bound technical evidence.
- `AVAILABLE` means the research computation completed; `NO_DECISION` remains a legitimate
  result. Rule scores are labeled `HEURISTIC_SCORE`, target-distance output is labeled
  `TARGET_DISTANCE_HEURISTIC_PROXY`, and neither is presented as calibrated probability or
  expected return.
- Quantitative trade-specialist runtime remains explicitly unbound. The post-campaign public
  activation can run four independently prompted, Google-Search-grounded Gemini context
  specialists plus a bounded Bull/Bear debate when configuration and quota are available.
  Code-only context verification runs, but trade Verification remains rejected without the
  approved Quantitative/Derivatives/Technical set. Risk always returns zero exposure with
  `RESEARCH_ONLY_NO_EXECUTION_AUTHORITY`.
- Bounded, locked and idempotent in-process store with in-flight request deduplication,
  immutable scope fingerprints and 409 rejection on request-id reuse across scopes.
- Restricted local dashboard CORS with no credentials and narrow methods/headers.
- Dashboard run action with loading/error/empty/available/unavailable states and inspectable
  Agent, Debate, Evidence, Verification/Risk, Prediction History and System Health panels.
- Agent Inspector shows each grounded LLM's view, risk label and clickable citation URLs;
  system health distinguishes configured local wiring from runtime call success.
- BTC/ETH and timeframe controls are wired into analysis; scope changes abort/ignore stale
  responses and clear old analysis. Forming candles are excluded from the displayed closed
  candle series.
- Chat health is probed separately. When Gemini configuration is absent, chat controls are
  disabled with an explicit reason while deterministic research analysis remains usable.
- Dashboard health probes only the local health endpoint, not exchange availability.

## Verification

- Focused runtime/API/chat/adapter/projection tests: 31 passed.
- Frontend tests: 8 passed.
- Frontend production build: passed (one non-blocking chunk-size warning).
- `npm audit`: 0 vulnerabilities.
- Full Python pytest: 635 passed, 12 skipped, 0 failed.
- Ruff/diff: clean; full mypy has 183 existing errors in 69 files, below the 202-error
  campaign-final baseline and with no error in the new runtime/API files.
- Real browser acceptance: BTC/USDT 4h and ETH/USDT 1h both returned `AVAILABLE`,
  `NO_DECISION`, five explicit agent/runtime states and 13 public technical evidence records.
- Independent review findings for temporal lineage, idempotency races, UI scope attribution,
  heuristic-return labeling and unverified approval state were fixed and regression-tested.
- Final review also caught forming-candle contamination in the legacy projection path,
  cancellation propagation across idempotent followers and narrow-screen toolbar overflow.
  Training/inference now enforce closed-and-published boundaries with invariance tests,
  follower waits are cancellation-isolated, and mobile controls stack with a local scrolling
  timeframe strip.

No secrets are returned. No live trading, private API or real-order endpoint was introduced.
This remains a research surface, not an approved Phase 6–9 trade authority chain. The UI never
presents context verification as an approved prediction or execution authorization.
