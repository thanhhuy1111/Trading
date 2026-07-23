# BASELINE EVIDENCE (before remediation)

Captured on branch `fix/paper-runtime-remediation`, baseline commit `chore: baseline before runtime remediation`.

Environment: Python 3.10.10 (project targets 3.12; 3.12 not available here), Node v25.6.1 / npm 11.9.0. `mypy`, `alembic`, `hypothesis`, `docker` NOT installed; Postgres/Redis unavailable.

| Command | Exit | Result |
|---|---|---|
| `python3 -m ruff check .` | 0 | PASS ("All checks passed!") |
| `python3 -m pytest tests/unit -q` | 0 | PASS — 109 passed |
| `python3 -m pytest tests/integration` | — | NOT RUN (needs Postgres/Redis) |
| `mypy .` | — | NOT RUN (not installed) |
| `alembic upgrade head` | — | NOT RUN (not installed / no DB) |
| `docker compose config` | — | NOT RUN (docker not installed) |
| `cd apps/dashboard && npm run build` | 0 | PASS (tsc + vite, 588ms) |

No pre-existing failing tests were hidden. These are the true baseline results the remediation must not regress.
