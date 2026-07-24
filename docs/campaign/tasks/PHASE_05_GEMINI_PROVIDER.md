# Phase 05 — Gemini Structured Provider

## Status

**COMPLETE**

## Research

Existing reusable components:

- `packages/chat_agent/provider.py` already defines a provider-neutral tool-calling boundary
  and deterministic fake.
- `packages/chat_agent/gemini_provider.py` is the sole SDK boundary for chat tool calls.
- `packages/llm/framework.py` already provides timeout/retry/circuit-breaker and safe disabled
  agent patterns.
- `google-genai>=2.14.0,<3.0.0` is already a direct dependency.

Missing Phase 5 capabilities were a generic structured-output provider for subsequent
specialist agents, strict Pydantic response validation, immutable prompt registry,
configuration-only health, and honest token/latency/version telemetry.

Official references:

- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/index.html)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)

The SDK/API supports JSON-schema structured output, but application-level Pydantic validation
is still mandatory. Model availability and quotas depend on account/project, so the model ID
is environment configuration and no live discovery/API call is performed in tests.

## Scope and architecture

- `PromptRegistry` is exact `(name, version)`, append-only and checksum-addressed.
- `StructuredLLMProvider` is provider-neutral and returns typed status/output/telemetry.
- `GeminiStructuredProvider` uses strict JSON schema plus `model_validate_json`; it never
  extracts JSON from prose or repairs malformed output.
- Missing key/model/structured mode returns `NOT_CONFIGURED` with null output.
- Health reports only local configuration (`CONFIGURED`), never fabricates remote health.
- Timeout, rate limit and transient failures retry at most the configured bound; invalid
  structured output is terminal and is not retried.
- Token counts stay `None` when the provider does not report them.
- Prompt/model versions, prompt checksum, request ID, attempts and latency are retained.
- API key is excluded from model representations/telemetry, and sensitive prompt variable
  names or the configured key value are rejected before transport.
- All Phase 5 tests inject a scripted transport. No real Gemini request is allowed.

## Files

- `packages/llm/prompt_registry.py`
- `packages/llm/structured_provider.py`
- `packages/llm/gemini_structured.py`
- `packages/chat_agent/config.py`
- `packages/chat_agent/gemini_provider.py`
- `apps/api/routers/chat.py`
- `.env.example`
- `tests/unit/test_gemini_structured_provider.py`

## Acceptance criteria

- [x] Provider Protocol and Gemini adapter use configured provider/model ID.
- [x] Structured JSON is schema-constrained and strictly Pydantic-validated.
- [x] Malformed, semantically invalid and extra-field output fails closed.
- [x] Timeout, rate-limit and transient retry are bounded.
- [x] Retry repeats the identical side-effect-free generation request.
- [x] Prompt registry is exact-version, append-only and checksummed.
- [x] Model ID, prompt version/checksum, attempts, latency and optional tokens are recorded.
- [x] Missing configuration returns safe health/result and does not construct/call a client.
- [x] Secrets are not hardcoded, logged, serialized or sent in prompt variables.
- [x] Tests use only mocks/scripted transport; no real Gemini API call.
- [x] No live trading, private exchange API, order or withdrawal behavior is added.

## Verification

- Phase-focused provider/LLM/chat compatibility tests: 60 passed.
- Full pytest: 554 passed, 12 skipped, 1 known Alembic baseline failure.
- Ruff: clean.
- Mypy: 180 errors in 67 files, unchanged baseline.
- Independent final review: no CRITICAL/HIGH/MEDIUM findings.

Known LOW limitation: SDK 429 classification currently uses stable message markers because the
SDK exception hierarchy is not exposed through the transport contract. Misclassification can
only change a bounded retry reason; it cannot make retries unbounded or produce an output.
