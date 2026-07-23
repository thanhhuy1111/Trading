# LLM Agent Framework (Phase 9)

`packages/llm/{framework,agents}.py`. Every concrete agent actually instantiated in this
codebase is disabled - none calls a real LLM provider, and none claims to. This module is the
fuller contract a real provider-backed agent implements later without any caller
(`BaselineMarketContextService`, the recommendation runtime) changing.

## The 5 named interfaces (`packages/llm/agents.py`)

`NewsAgentPort`, `MacroAgentPort`, `SentimentAgentPort`, `RiskCriticAgentPort` - all
`async def assess(symbol, as_of_time) -> MarketContextAssessment`. `CoordinatorAgentPort` -
`async def coordinate(assessments: List[MarketContextAssessment]) -> List[MarketContextAssessment]`,
structurally unable to emit its own probability/price/risk override since its signature only
accepts and returns `MarketContextAssessment` lists.

`packages.intelligence.market_context`'s Phase 4 no-op agents (`NoOpNewsAgent`, etc.) already
satisfy these Protocols structurally and are left untouched - not duplicated, not replaced -
per the preserve-existing-behavior rule. `packages/llm/agents.py` additionally provides
`DisabledLLMAgent`-backed `NewsAgent`/`MacroAgent`/`SentimentAgent`/`RiskCriticAgent` classes
for a caller that wants the richer `LLMAgentConfig` explicitly attached, and
`PassThroughCoordinatorAgent`, the only coordinator implementation in this task.

## `LLMAgentConfig`

`agent_name`, `agent_version`, `prompt_version`, `timeout_seconds` (10s default), `max_retries`
(2), `circuit_breaker_failure_threshold` (5), `circuit_breaker_reset_seconds` (60),
`allowed_tools` (empty `frozenset` by default - **no tool use permitted** unless explicitly
listed).

## `BaseLLMAgent` / `DisabledLLMAgent`

`BaseLLMAgent.assess()` wraps `_call_provider()` with timeout + bounded retry +
`CircuitBreaker`, and always degrades to a `NOT_AVAILABLE` `MarketContextAssessment` on
timeout or any provider exception - it never raises to the caller and never fabricates a view.
`DisabledLLMAgent` (what every concrete agent in this task actually is) bypasses the
retry/circuit-breaker machinery entirely and returns `NOT_AVAILABLE` immediately, since a
provider that structurally does not exist has nothing to retry.

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

## Runtime independence

`packages.runtime.recommendation_service` never imports `packages.llm`'s provider clients, and
the full pipeline is tested and works with every LLM agent disabled - see
`tests/acceptance/test_final_acceptance.py` for the end-to-end demonstration.
