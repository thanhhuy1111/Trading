# REVIEW PLAN — Independent System Review (READ ONLY)

**Date:** 2026-07-23
**Reviewer roles:** Principal Software Architect · Quant Trading System Reviewer · Application Security Reviewer · SRE · Financial Ledger/Reconciliation Reviewer
**Mode:** REVIEW ONLY. No source changes, no live trading, no private exchange API, no destructive DB ops.

## Scope & constraints
- Only read/search code, read docs, run lint/tests/build, static docker check, offline migration inspection.
- Verify `LIVE_TRADING_ENABLED=false` and `PRIVATE_EXCHANGE_API_ENABLED=false`.
- Flag any code path capable of placing real orders as `CRITICAL — LIVE TRADING BOUNDARY VIOLATION` (do not trigger it).

## Repository facts (established)
- Python 3.12 monorepo, ~12.4k LOC in `packages/`, FastAPI app in `apps/api`, React/Vite dashboard in `apps/dashboard`.
- Infra: Postgres 16, Redis 7, ClickHouse, Redpanda (docker-compose profiles minimal/full).
- 12 Alembic migrations; 24 API routers; ~46 test modules.
- **Git repo has zero commits** — entire tree is uncommitted working state.
- Official commands (Makefile): `make test` (pytest), `make lint` (ruff), `make typecheck` (mypy), `make migrate` (alembic upgrade head), `make dev-api`, `make dev-dashboard`.

## Work plan
1. Map real architecture from code (entrypoints, pipelines, wiring) vs. docs. ✅
2. Enumerate agents & extract exact logic/thresholds. ✅
3. LLM/API detection across source + deps. ✅
4. Market data / Data Guardian fail-closed review. ✅
5. Feature engine lookahead audit. ✅
6. Critic / Consensus / Meta-Allocator invariants. ✅
7. Risk Governor veto + Decimal + bypass search. ✅
8. Execution & paper exchange fill correctness / idempotency / restart. ✅
9. Ledger / position / PnL / NAV accounting. ✅
10. Backtest reliability, lookahead, same-bar-fill, reproducibility. ✅
11. Paper trading readiness (isolation, recovery, ingestion loop). ✅
12. Dashboard explainability. ✅
13. Security & live-trading boundary (multi-layer). ✅
14. Quality gates: ruff, pytest, frontend build, docker (static), migrations (offline). ✅ (limits noted)
15. Findings register + remediation plan + final decision. ✅

## Environment limitations (affect "runtime verified" claims)
- `mypy`, `alembic` not installed in this environment (dev extras not installed) → typecheck and live migration not executed.
- `docker` not installed → `docker compose config`/`build` not executed.
- Integration tests (`tests/integration/*`) require Postgres/Redis → not executed; only `tests/unit` run.
- No exchange credentials used; no private API calls made.

Subagents were **not** spawned; review performed directly with read-only tools.
