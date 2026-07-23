# COMMAND EVIDENCE

Environment: macOS (darwin 25.5.0), Python 3.10.10 (note: project requires 3.12; ran with available 3.10), Node v25.6.1 / npm 11.9.0. Dev extras (`mypy`, `alembic`, `hypothesis`) not installed; `docker` not installed; Postgres/Redis not available.

| # | Command | Exit | Result | Notes |
|---|---|---|---|---|
| 1 | `python3 -m ruff check .` | 0 | **PASS** | "All checks passed!" |
| 2 | `python3 -m pytest tests/unit -q` | 0 | **PASS** | 109 passed, 2 warnings, 0.25s (`asyncio_mode` unknown-option warning under pytest w/o pytest-asyncio) |
| 3 | `python3 -m pytest tests/integration` | — | **NOT RUN** | Requires Postgres/Redis; skipped per read-only/no-infra constraint |
| 4 | `mypy .` | — | **NOT RUN** | `mypy` not installed (dev extras absent) |
| 5 | `python3 -m alembic history` | — | **NOT RUN** | `alembic` not installed; 12 migration files present (`001`–`012`), inspected statically |
| 6 | `docker compose config` | 127 | **NOT RUN** | `docker` not installed on host |
| 7 | `docker compose build` | — | **NOT RUN** | `docker` not installed |
| 8 | `npm run build` (apps/dashboard) | 0 | **PASS** | `tsc && vite build` → 32 modules, built in 588ms, `dist/assets/index-*.js` 221.6 kB |
| 9 | `npm run lint` (apps/dashboard) | — | **NOT RUN** | No `lint` script defined in `package.json` (only dev/build/preview) |
| 10 | `npm test` (apps/dashboard) | — | **NOT RUN** | No `test` script defined |

## Static scans performed (read-only greps)
- **LLM/AI providers** (`openai|anthropic|claude|gemini|google.generativeai|mistral|cohere|groq|ollama|litellm|langchain|langgraph|llamaindex|transformers|huggingface|chat.completions|responses.create|messages.create|generate_content`): **0 hits** in source, tests, `pyproject.toml`, `package.json`, docker-compose, `.env`.
- **Hardcoded secrets** (`secret|api_key|password|token|private_key = "<12+ chars>"`): **0 hits** in `packages/`+`apps/` (excluding placeholders/redactor field lists). `.env` uses `testnet_..._placeholder`.
- **Live-boundary flags:** `LIVE_TRADING_ENABLED`/`PRIVATE_EXCHANGE_API_ENABLED` default `False` (`packages/common/config.py:19-21`); `.env` sets `LIVE_TRADING_ENABLED=false`. Startup asserts (`apps/api/main.py:39-42`) raise if true.
- **Binance adapter:** public endpoints only (`REST_BASE_URL=https://api.binance.com`, `/api/v3/klines`, `/api/v3/depth`, public WS); no signing/keys/order endpoints (`packages/market_data/adapters/binance.py`).
- **Pipeline caller trace:** `run_agents`, `process_signals`, `process_candle_close`, `process_public_candle` → **no production callers** (tests only).

## `.env` vs `.env.example`
Identical. `SYSTEM_MODE=PAPER_TRADING`, `LIVE_TRADING_ENABLED=false`, `FEATURE_FLAGS_LIVE_TRADING=false`, `BINANCE_TESTNET=true`, keys = placeholders.
