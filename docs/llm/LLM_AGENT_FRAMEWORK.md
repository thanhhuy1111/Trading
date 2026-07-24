# LLM Agent Framework (Phase 9)

`packages/llm/{framework,agents,grounded_context,context_debate}.py`. The disabled baseline
remains the default when Gemini is not configured. When `GEMINI_API_KEY`, `GEMINI_MODEL` and
`GEMINI_CONTEXT_ENABLED=true` are present, the public research runtime instantiates four
provider-backed logical specialists and a bounded two-sided debate.

## The 5 named interfaces (`packages/llm/agents.py`)

`NewsAgentPort`, `MacroAgentPort`, `SentimentAgentPort`, `RiskCriticAgentPort` - all
`async def assess(symbol, as_of_time) -> MarketContextAssessment`. `CoordinatorAgentPort` -
`async def coordinate(assessments: List[MarketContextAssessment]) -> List[MarketContextAssessment]`,
structurally unable to emit its own probability/price/risk override since its signature only
accepts and returns `MarketContextAssessment` lists.

`packages.intelligence.market_context`'s Phase 4 no-op agents (`NoOpNewsAgent`, etc.) remain
available for offline recommendation/runtime tests. The activated public analysis surface
uses `GroundedGeminiContextAgent` instances named `news_agent`, `macro_agent`,
`sentiment_agent` and `risk_critic_agent`. They share a configured Gemini model but execute
independent calls, prompts and response validation.

## Grounded provider runtime

- Uses Gemini's Interactions API with the built-in `google_search` tool and strict JSON-schema
  output.
- Accepts source IDs only from `url_citation` annotations on model-output steps. URLs written
  merely inside model JSON are never treated as provenance.
- Requires at least one public HTTP(S) citation per available specialist.
- Stores citation URL and retrieval time; it explicitly does not claim the retrieval timestamp
  is the source's publication timestamp.
- Labels confidence as an LLM heuristic, not a calibrated probability.
- Forces `risk_adjustment=0`; context agents cannot alter portfolio or execution risk.
- Uses zero retries by default and a five-analysis-per-minute process guard to bound paid calls.

When all four grounded specialists succeed, `ContextDebateService` runs one independent Bull
and one independent Bear structured-output call. Debate source IDs must be a subset of the
already admitted specialist citations. Numeric claims in debate prose are rejected.

## `LLMAgentConfig`

`agent_name`, `agent_version`, `prompt_version`, `timeout_seconds` (10s default), `max_retries`
(2), `circuit_breaker_failure_threshold` (5), `circuit_breaker_reset_seconds` (60),
`allowed_tools` (empty `frozenset` by default - **no tool use permitted** unless explicitly
listed).

## `BaseLLMAgent` / `DisabledLLMAgent`

`BaseLLMAgent.assess()` wraps `_call_provider()` with timeout + bounded retry +
`CircuitBreaker`, and always degrades to a `NOT_AVAILABLE` `MarketContextAssessment` on
timeout or any provider exception - it never raises to the caller and never fabricates a view.
`DisabledLLMAgent` bypasses retry/circuit-breaker machinery and returns `NOT_AVAILABLE`
immediately. It remains the fail-closed behavior when configuration is absent.

## Defensive requirements (structural, not just documented convention)

- **No secrets/keys/balances in a prompt.** `redact_sensitive_fields(payload)` strips any
  payload key whose name matches a secret/key/token/password/balance/credential/private
  marker, fail-closed (redacts when uncertain).
- **Prompt injection is flagged, never silently dropped.** `detect_prompt_injection(text)`
  returns known injection patterns found in externally-sourced text (news headlines, social
  content) - the caller is expected to fold non-empty results into `reason_codes`/`limitations`.
- **No unvalidated LLM output reaches a domain entity.** `validate_structured_output(payload)`
  checks a provider's raw JSON against the required fields and bounds (confidence in [0,1],
  risk_adjustment in [-1,1], view is a string) before any `MarketContextAssessment` is built
  from it - rejects rather than raises, so a malformed response degrades to
  `INVALID_RESPONSE`.
- **No unbounded tool use.** `check_tool_allowed(config, tool_name)` - empty allowlist by
  default means no tool calls of any kind.

## Verification and runtime independence

`packages.runtime.recommendation_service` never imports `packages.llm`'s provider clients, and
the full pipeline is tested and works with every LLM agent disabled - see
`tests/acceptance/test_final_acceptance.py` for the end-to-end demonstration.

The public multi-LLM runtime performs code-only citation/set verification. Even when context
and debate verify successfully, trade Verification remains `REJECTED` until the existing
Technical + Derivatives + approved Quantitative specialist contract is satisfied. This
activation does not loosen that gate and Risk continues to return zero exposure.
