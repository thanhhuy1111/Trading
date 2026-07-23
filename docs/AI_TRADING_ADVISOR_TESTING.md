# AI TRADING ADVISOR — TESTING

## 1. Environment

This repo's `pyproject.toml` requires Python 3.12+; a stock macOS `python3` may be 3.10.
The dev workflow used to build and verify this feature:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/unit -q
```

## 2. Default suite is fully offline

Every test added for this feature runs with **no network access and no `GEMINI_API_KEY`**:

- `tests/unit/test_recommendation_domain.py` (20 tests) — proposal builder/validator/
  ranker/cost-service, hand-built fixtures, no I/O.
- `tests/unit/test_prediction_service.py` (20 tests) — direction/return/volatility/meta-
  label models, calibration/evaluation metrics, `PredictionService` with an empty and a
  populated in-memory `ModelRegistry`.
- `tests/unit/test_evidence_service.py` (10 tests) — `EvidenceRegistry` approval policy.
- `tests/unit/test_recommendation_service.py` (6 tests) — `RecommendationService` against
  `MockMarketDataProvider` and a hand-built `_UptrendMarketDataProvider` fixture (reuses
  the proven candle-generation pattern from `tests/unit/test_decision_pipeline_e2e.py`);
  proves the default (empty registries) path never reaches `PROPOSALS_AVAILABLE`.
- `tests/unit/test_chat_agent.py` (31 tests) — guardrails, `ToolRegistry` allowlist/schema
  validation, `TradingAdvisorOrchestrator` bounded loop (round cap, prompt-injection
  short-circuit, malformed/unsupported tool call survival), full golden-path run with
  `FakeLLMProvider`, and a static source-scan proving no execution/private-exchange symbol
  is referenced.
- `tests/unit/test_advisor_api.py` (8 tests) — FastAPI `TestClient` against all 5 new
  routes with every service dependency overridden via `app.dependency_overrides` (no
  network); API-key enforcement.

Run just this feature's tests:

```bash
pytest tests/unit/test_recommendation_domain.py tests/unit/test_prediction_service.py \
       tests/unit/test_evidence_service.py tests/unit/test_recommendation_service.py \
       tests/unit/test_chat_agent.py tests/unit/test_advisor_api.py -v
```

Run the full repository unit suite (includes this feature's tests plus everything already
in the repo, e.g. `fix/paper-runtime-remediation`'s tests):

```bash
pytest tests/unit -q
```

## 3. Why `FakeLLMProvider`, not a mocked Gemini SDK

`packages/chat_agent/provider.py::FakeLLMProvider` implements the exact golden-path
sequence from the implementation plan's system prompt (call `get_market_overview` first,
then `scan_trade_opportunities`, then format a final answer) using only the
provider-agnostic `AgentRequest`/`AgentProviderResult` contract — it never imports
`google.genai`. This means:

- Tests exercise the REAL orchestrator loop logic (round/call limits, transcript
  bookkeeping, tool execution, guardrails) exactly as production would run it.
- Tests never depend on Gemini's actual behavior, so they can't be flaky because of a
  model version change or an API outage.
- No `GEMINI_API_KEY` is needed for CI.

## 4. What determinism is (and isn't) proven

`test_builder_is_deterministic_for_identical_inputs`,
`test_evaluate_approval_is_deterministic`, and the ranker ordering tests prove that given
the same `TradeCandidate` + `ModelPrediction` + `StrategyEvidence` + config, the resulting
proposal/score/ranking is byte-identical. This is proven at the domain-logic layer, not
via two full end-to-end scans, because two real scans a few seconds apart will legitimately
see slightly different market data (different candles) — that is expected, not a
determinism bug.

## 5. Optional live Gemini smoke test — NOT IMPLEMENTED

See `docs/AI_TRADING_ADVISOR_GEMINI_SETUP.md` §6. No `GEMINI_API_KEY` was available while
building this feature, so `GeminiProvider` itself has zero test coverage against the real
API. This is the single largest testing gap in this feature. Do not treat `GeminiProvider`
as verified until that smoke test exists and has been run at least once with a real key.

## 6. Commands run and results (this implementation)

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | PASSED (0 errors, full repo) |
| Unit tests | `pytest tests/unit -q` | PASSED (245/245, includes all pre-existing tests) |
| Type check | `mypy packages/recommendation packages/prediction packages/chat_agent apps/api/routers/{chat,recommendations}.py apps/api/dependencies.py` | PARTIAL — real `Optional`-narrowing bugs mypy caught in the new code were fixed (see git log); remaining errors are (a) a repo-wide `pyproject.toml` gap: no `plugins = pydantic.mypy`, so mypy doesn't recognize `BaseModel.model_validate`/`model_json_schema` as real attributes, and (b) pre-existing strict-mode debt in `packages/market_data`, `packages/features`, `packages/agents` predating this feature. `mypy services apps packages` (the full repo, per the Makefile) was not run to completion — see `docs/review/COMMAND_EVIDENCE.md`, which already documents mypy as not previously runnable in the reviewed environment |
| Integration tests | `pytest tests/integration -q` | NOT RUN — pre-existing tests in this suite require a live Postgres instance not available in this environment (unrelated to this feature) |
| Frontend build | — | SKIPPED — no frontend files were changed by this feature |
| Live Gemini smoke test | — | BLOCKED — no `GEMINI_API_KEY` available; see §5 |
