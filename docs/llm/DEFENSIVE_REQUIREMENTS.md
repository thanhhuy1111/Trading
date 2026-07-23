# LLM Defensive Requirements

This document collects, in one place, every rule this codebase enforces about how the LLM
layer is allowed to interact with the rest of the system - each rule links to where it's
structurally enforced (not merely documented) and to the test that verifies it.

| Rule | Enforcement | Test |
|---|---|---|
| No secrets/keys/balances sent to an LLM | `packages.llm.framework.redact_sensitive_fields` | `test_redact_sensitive_fields_strips_keys_secrets_and_balances` |
| Prompt injection in external text is flagged, not silently accepted | `packages.llm.framework.detect_prompt_injection` | `test_detect_prompt_injection_flags_known_patterns` |
| No LLM-generated prices/indicators/evidence/probabilities/risk overrides | `packages.risk.portfolio_governor` has no import path to `packages.llm`/`packages.intelligence`; `CoordinatorAgentPort.coordinate()`'s signature only accepts/returns `MarketContextAssessment` lists | `docs/governance/PORTFOLIO_RISK_GOVERNOR.md` "Structural isolation" |
| No unvalidated LLM output reaches a domain entity | `packages.llm.framework.validate_structured_output` | `test_validate_structured_output_rejects_missing_and_out_of_bounds_fields` |
| No unbounded tool use | `LLMAgentConfig.allowed_tools` defaults to `frozenset()` | `test_tool_allowlist_defaults_to_empty_no_tools_permitted` |
| The runtime works with every LLM agent disabled | `BaselineMarketContextService`'s default agents are all no-ops; `packages.runtime.recommendation_service` never requires a non-`NOT_AVAILABLE` context assessment | `tests/acceptance/test_final_acceptance.py` |
| An LLM/provider failure never raises to the caller | `BaseLLMAgent.assess()` catches `TimeoutError` and any provider exception, always returns a typed `NOT_AVAILABLE` result | `test_base_llm_agent_degrades_to_not_available_on_timeout_never_raises`, `test_base_llm_agent_never_raises_on_provider_failure` |
| A repeatedly-failing provider is circuit-broken, not retried forever | `packages.llm.framework.CircuitBreaker` | `test_circuit_breaker_opens_after_threshold_and_resets_after_window` |

## What is explicitly out of scope in this task

No real LLM provider client is implemented or configured anywhere in this codebase. Every
concrete agent (`NewsAgent`, `MacroAgent`, `SentimentAgent`, `RiskCriticAgent`,
`PassThroughCoordinatorAgent`, and the pre-existing `NoOp*` agents in
`packages.intelligence.market_context`) is a disabled/no-op implementation. Wiring a real
provider (API keys, network calls, model selection) is future work, and when it happens it
must go through `packages.llm.framework.BaseLLMAgent` so the reliability/defensive plumbing in
this document applies automatically rather than being re-derived per-agent.
