# AI TRADING ADVISOR — GEMINI SETUP

## 1. Install

This repo uses `pyproject.toml` (setuptools) with `pip install -e .`, not poetry/uv. The
Gemini SDK is a pinned core dependency (not a dev extra), since `GeminiProvider` is
production code:

```bash
pip install -e ".[dev]"
```

`google-genai>=2.14.0,<3.0.0` is declared in `pyproject.toml`. This project was built and
tested against `google-genai==2.14.0` specifically; if a newer major version changes the
`types.ThinkingConfig`/`types.FunctionDeclaration`/`generate_content` signatures used in
`packages/chat_agent/gemini_provider.py`, that file will need updating alongside the pin.

## 2. Environment variables

Set these in `.env` (never commit a real key — `.env.example` only has placeholders):

```bash
GEMINI_API_KEY=              # required for the /api/v1/chat route to work at all
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_THINKING_LEVEL=MINIMAL   # MINIMAL | LOW | MEDIUM | HIGH (maps 1:1 to google.genai.types.ThinkingLevel)
GEMINI_ENABLE_GOOGLE_SEARCH=false
GEMINI_REQUEST_TIMEOUT_SECONDS=30.0
GEMINI_MAX_RETRIES=2
```

If `GEMINI_API_KEY` is empty, `POST /api/v1/chat` returns `503` — the API never falls back
to a fixture or fabricated answer in that case (see `apps/api/routers/chat.py`).

## 3. Google Search policy

`GEMINI_ENABLE_GOOGLE_SEARCH` defaults to `false` and **must stay false** on the trade
recommendation path. Even when `true`, `GeminiProvider` only adds the `google_search` tool
to the tools list it builds — the orchestrator (`packages/chat_agent/orchestrator.py`)
only ever passes the fixed 5-tool allowlist from `packages/chat_agent/tool_registry.py` to
the provider, so search is never actually reachable from `/api/v1/chat` today regardless
of this flag. This flag exists for a future, separate, disabled-by-default "News Research"
capability (implementation plan §4) that is **not implemented** in this repository — do
not wire it into the recommendation path without also adding the `NewsInsight` typed
contract and keeping it strictly downstream of the quantitative gates.

## 4. Local startup

```bash
uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

Then:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Bây giờ tôi có thể đặt lệnh nào?"}'
```

In `ENVIRONMENT=development` with `ADVISOR_API_KEY` unset, no `X-API-Key` header is
required (logged once as a warning). In any other environment, or once `ADVISOR_API_KEY`
is set, requests must include a matching `X-API-Key` header or receive `401`.

## 5. Test commands

See `docs/AI_TRADING_ADVISOR_TESTING.md` for the full breakdown. Short version:

```bash
pytest tests/unit -q                 # default suite: no network, no GEMINI_API_KEY needed
```

## 6. Optional live smoke test

**Not implemented in this repository.** The plan calls for an opt-in test gated on
`GEMINI_API_KEY` + `RUN_GEMINI_LIVE_TESTS=1` that must never run in the default suite and
must never recommend a real order. No `GEMINI_API_KEY` was available in the environment
this feature was built in, so `GeminiProvider` has not been exercised against the live
API — it is built directly against the installed SDK's introspected type signatures
(see `packages/chat_agent/gemini_provider.py` module docstring) but is unverified.
Before relying on it: add a `tests/integration/test_gemini_live_smoke.py` marked
`@pytest.mark.skipif(not os.environ.get("RUN_GEMINI_LIVE_TESTS"), reason=...)` that sends
one real message through `GeminiProvider` + `ToolRegistry` and asserts a tool call and a
non-empty final answer, then run it manually with a real key before production use.

## 7. Key rotation

`GEMINI_API_KEY` is read once per `GeminiProvider` instantiation
(`packages/chat_agent/gemini_provider.py::GeminiProvider.__init__`) from
`GeminiSettings` (`packages/chat_agent/config.py`), which is a `pydantic-settings`
`BaseSettings` reading from the process environment / `.env`. To rotate: update the
secret in your environment/secret manager, then restart the API process (there is no
in-process hot-reload of the key, and none should be added without also re-auditing that
a raw key never ends up in a log line — see `packages/chat_agent/guardrails.py::redact_secrets`).
