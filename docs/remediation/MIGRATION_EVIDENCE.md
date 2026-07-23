# MIGRATION EVIDENCE

## Round 3
New migration **`013_paper_runtime_persistence`** (revises `012_security_hardening`, now head)
adds the session-scoped durable paper tables. Existing migrations `001`–`012` are unchanged.

Environment: `alembic` installed this round; **no PostgreSQL server available** → the live
`upgrade/downgrade/upgrade` cycle could NOT run.

| Command | Exit | Result | Notes |
|---|---|---|---|
| `alembic history` | 0 | PASS | chain intact, `013…` is head |
| `alembic heads` | 0 | PASS | single head `013_paper_runtime_persistence` |
| `alembic upgrade 012:013 --sql` (offline) | 0 | PASS | emits CREATE for 7 `paper_*` tables + unique constraints + indexes |
| `alembic downgrade 013:012 --sql` (offline) | 0 | PASS | emits DROP in FK-safe reverse order |
| `alembic upgrade head` (online) | — | **NOT RUN** | no PostgreSQL server |
| `alembic downgrade -1` (online) | — | **NOT RUN** | no PostgreSQL server |

The offline `--sql` generation runs the whole `001→013` chain in offline mode, so it confirms
013 composes with prior migrations and produces valid DDL — but it does NOT prove the cycle
applies/rolls back on a live database. That remains for a round with a disposable PostgreSQL.
