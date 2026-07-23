"""Durable paper-trading persistence layer (F-02/F-03/F-04/F-05).

Status: IMPLEMENTED_NOT_VERIFIED on PostgreSQL. No PostgreSQL server was available in the
build environment (no docker/initdb/psql), so migrations and integration drills could not be
executed. Design-level properties (DDL compiles for the postgresql dialect, unique constraints
present, transaction step ordering, idempotency branching, and reconciliation math) ARE verified
by unit tests with fakes. See docs/remediation/DATABASE_TRANSACTION_EVIDENCE.md and
docs/remediation/DB_IDEMPOTENCY_EVIDENCE.md.
"""
