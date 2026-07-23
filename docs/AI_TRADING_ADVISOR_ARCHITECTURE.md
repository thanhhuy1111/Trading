# AI TRADING ADVISOR — ARCHITECTURE

**Status:** Implemented on `feat/ai-trading-advisor` (branched from `fix/paper-runtime-remediation`, not `main`).
**Mode:** Recommendation / research only. No order is ever placed.

---

## 1. Why this branches from `fix/paper-runtime-remediation`, not `main`

At the time this feature started, `main` (and the review branch it was audited from) was
still at the pre-remediation baseline: the multi-agent decision chain existed in code but
was never invoked by any runnable pipeline (see `docs/review/FINDINGS_REGISTER.md` F-01).
`fix/paper-runtime-remediation` already wired the real chain into a reusable
`packages/governance/decision_service.py::DecisionService` used by both paper trading and
backtest. Building the advisor on the baseline would have meant reusing an intelligence
layer that never actually ran; building on the remediation branch means the advisor's
"quant engine" is the same real, tested code path already driving paper trading.

## 2. Repository audit summary (Phase 0)

| Existing module | Reused as-is | Notes |
|---|---|---|
| `packages/market_data/adapters/*` | Yes | `MarketDataProviderFactory`, `BinancePublicMarketDataProvider` (public only) |
| `packages/features/pipeline.py::feature_pipeline` | Yes | Called via `DecisionService`, and directly for `get_market_overview` |
| `packages/agents/*` (Regime/Trend/Reversion/Breakout) | Yes | Via `DecisionService`, unmodified |
| `packages/governance/{critic,consensus,allocator,decision_service}.py` | Yes | Unmodified |
| `packages/governance/cost_estimator.py` | Yes | Wrapped by `packages/recommendation/cost_service.py` for transparency, not reimplemented |
| `packages/risk/*`, `packages/execution/*` | **Not called** | Deliberately: this is recommendation-only, no position is sized or executed (see §5) |
| `packages/telemetry/metrics.py::metrics_registry` | Yes | New metric names added, existing cardinality policy respected |
| `packages/common/logger.py` | Yes | All new structured logs use it |

New packages built for this feature (none of the above needed to be duplicated):

```
packages/recommendation/   domain models, proposal pipeline, evidence registry
packages/prediction/       prediction service interfaces + pure-arithmetic inference
packages/chat_agent/       LLM provider abstraction, tool registry, orchestrator
apps/api/routers/{chat,recommendations}.py
```

## 3. Data flow (as built)

```
User "Bây giờ tôi có thể đặt lệnh nào?"
  -> POST /api/v1/chat
  -> TradingAdvisorOrchestrator (bounded tool loop)
  -> LLMProvider.complete_with_tools()   [GeminiProvider or FakeLLMProvider]
  -> ToolRegistry.execute("get_market_overview" | "scan_trade_opportunities" | ...)
  -> RecommendationService
       -> MarketDataProviderFactory (Binance public REST, no keys)
       -> FeaturePipeline.compute()                    [reused, unmodified]
       -> DecisionService.decide()                      [reused, unmodified]
            -> MarketRegimeAgent / TrendAgent / MeanReversionAgent / BreakoutAgent
            -> CriticAgent -> SignalConsensusEngine -> MetaAllocator
            -> TradeIntent(side=BUY, status=PENDING_RISK_REVIEW) | None
       -> PredictionService.predict()                   [NEW]
       -> EvidenceService.get_evidence()                [NEW]
       -> proposal_validator.check_candidate_gates()     [NEW]
       -> proposal_builder.build()                       [NEW]
       -> opportunity_ranker.rank()                       [NEW]
  -> RecommendationResult (PROPOSALS_AVAILABLE | NO_TRADE | ...)
  -> ToolResult fed back to the model
  -> Gemini formats the grounded final answer from ToolResult facts only
  -> ChatTurnResult -> ChatResponse
```

`RecommendationService` never imports or calls `packages.execution.engine.ExecutionEngine`,
`packages.paper.adapter.PaperExchangeAdapter`, or any private-exchange symbol. This is
enforced by a static-source-scan test
(`tests/unit/test_chat_agent.py::test_new_modules_never_reference_execution_or_private_exchange_symbols`),
not just a design intention.

## 4. Why proposals require BOTH a calibrated prediction AND approved evidence

Two invariants intersect here and they are easy to conflate:

- `AgentSignal.confidence` / `TradeIntent.expected_return_bps` are **heuristic, rule-based
  proxies** (see `packages/agents/pricing.py` docstring: "transparent placeholder proxy,
  NOT a calibrated forecast"). They existed before this feature and are unchanged.
- `ModelPrediction.probability_profit` must come from a **calibrated statistical/ML
  model** registered in `packages/prediction/registry.py`.

**No trained model artifact ships in this repository.** `packages/prediction/registry.py`'s
`model_registry` is empty by construction. Consequently `PredictionService.predict()`
always returns `calibration_status=UNAVAILABLE`, `ProposalBuilder.build()` always returns
`None`, and `scan_trade_opportunities` always resolves to `INSUFFICIENT_EVIDENCE` or
`STRATEGY_NOT_APPROVED` in this repository's current state — **never** `PROPOSALS_AVAILABLE`
with real market data, by design. The integration tests that DO exercise the
`PROPOSALS_AVAILABLE` path (`tests/unit/test_recommendation_service.py`,
`tests/unit/test_chat_agent.py`, `tests/unit/test_advisor_api.py`) explicitly register a
fixture `ModelArtifact` and a fixture `StrategyEvidence(status=APPROVED)` first — this is
never the default, and is never reachable from the production API without a real training
pipeline populating the registry.

This is the single most important fact about this feature's current state: **the pipeline
is real end-to-end, but it has no trained model or out-of-sample evidence behind it yet.**
See §7 for what would be needed to close that gap.

## 5. Non-negotiable safety invariants — how each is enforced in code

| Invariant | Enforcement |
|---|---|
| LLM cannot execute orders | No import of `packages.execution` or `packages.paper` anywhere in `packages/chat_agent` or `packages/recommendation`; proven by static scan test |
| LLM cannot access private exchange credentials | `RecommendationService` only ever constructs `MarketDataProviderFactory.create_provider("binance")` (public REST); no `BINANCE_SECRET_KEY`/`BINANCE_API_SECRET` referenced anywhere in new code |
| LLM cannot compute final position quantity | `TradeProposal` has no `quantity`/`notional` field (matches the existing `TradeIntent`/`AgentSignal` safety validators) |
| LLM cannot bypass Risk Governor | The advisor never calls `packages.risk.governor`; it doesn't size or approve orders at all, so there's nothing to bypass |
| LLM cannot invent prices/indicators/probabilities/evidence | Every numeric field in a `TradeProposal` traces to a `TradeCandidate` (from `DecisionService`) or a `ModelPrediction` (from `PredictionService`); the LLM only ever sees `.model_dump(mode="json")` output of these typed models via `ToolResult.output` |
| LLM cannot approve an unapproved strategy | `check_candidate_gates` rejects any candidate whose `EvidenceStatus != APPROVED` |
| LLM cannot enable live trading | No route, tool, or model field exists to set `LIVE_TRADING_ENABLED`; the base app's startup kill switch (`apps/api/main.py` lifespan) is untouched |
| `NO_TRADE` always available | `RecommendationStatus.NO_TRADE` is a first-class outcome, not an exception path |
| Every proposal has an expiry | `TradeProposal.expires_at`, enforced by `proposal_validator.validate_proposal` |
| Every proposal includes uncertainty and risk | `probability_profit`, `expected_downside_bps`, `risk_flags`, `invalidation_conditions` are required fields |

## 6. Known gaps (do not hide these)

1. **No trained prediction model.** `packages/prediction/registry.py` ships empty. §4 above.
2. **No out-of-sample strategy evidence.** `packages/recommendation/evidence_service.py`'s
   registry ships empty; every strategy starts `INSUFFICIENT`.
3. **No dataset/label pipeline.** The implementation plan's Phase B (dataset builder,
   triple-barrier labels, purge/embargo, walk-forward evaluation) is not implemented.
   `packages/prediction/evaluation.py` and `calibration.py` provide the pure metric
   functions an offline training script would need, but the script itself does not exist.
4. **No durable conversation storage.** `InMemoryConversationRepository` only; history is
   lost on process restart. A durable implementation would need to reuse this repo's
   existing `packages/persistence` Postgres infrastructure (from `fix/paper-runtime-
   remediation`) — not implemented here to avoid touching a database this task was told
   not to assume is safely reachable.
5. **No shadow-mode outcome tracking** (implementation plan Phase F). Proposals are
   generated and stored (`ProposalStore`), but nothing evaluates predicted-vs-realized
   return after `horizon_minutes` elapses.
6. **No chat UI.** Backend/API only, per the plan's explicit "do not start by building the
   UI" instruction.
7. **GeminiProvider is unverified against the live API** (no `GEMINI_API_KEY` was available
   in the build environment). See `docs/AI_TRADING_ADVISOR_TESTING.md`.
8. **Only one prediction horizon is realistic today.** Every agent hardcodes its own
   `horizon_minutes` (30/45/60) independent of what a caller requests; `scan_trade_
   opportunities` accepts `horizons_minutes` in its input schema for forward compatibility
   but does not filter by it (see `packages/chat_agent/tool_registry.py` module docstring).
9. **Two bugs in the pre-existing `BinancePublicMarketDataProvider` were found and worked
   around defensively (not fixed at the source)** while building and testing this feature:
   it marks every returned kline `is_closed=True` even when the interval hasn't actually
   closed yet. `RecommendationService._fetch_candles` now drops any candle whose
   `close_time` is still in the future before using it. The root cause in
   `packages/market_data/adapters/binance.py` is unchanged, since it is shared by paper
   trading and backtest and fixing it was out of this feature's scope.

## 7. What "closing the loop" would require (not built here)

To reach implementation-plan Phase A ("READY FOR SHADOW RECOMMENDATION"): a historical
OHLCV dataset registry + point-in-time feature/label builder with purge/embargo, an
offline training script producing `LogisticRegressionWeights`/`LinearRegressionWeights`
artifacts registered into `model_registry`, a walk-forward backtest run producing a real
`StrategyEvidence` record registered into `evidence_registry`, and a shadow-mode scheduler
persisting `RecommendationResult`s and grading them against realized outcomes. All the
downstream typed interfaces this would plug into already exist and are tested against
fixtures; none of the upstream data/training work exists yet.
