"""Durable paper-trading persistence integration drills (PostgreSQL required).

These are SKIPPED unless a disposable PostgreSQL is provided via the ``PAPER_DB_TEST_URL``
environment variable (async DSN, e.g. postgresql+asyncpg://user:pass@localhost:5432/paper_test).
They MUST run against real PostgreSQL — never SQLite — before F-03/F-04 can be marked verified.

Status this round: NOT RUN (no disposable PostgreSQL available in the build environment).
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("PAPER_DB_TEST_URL"),
    reason="PAPER_DB_TEST_URL not set: no disposable PostgreSQL available (see REMAINING_LIMITATIONS.md)",
)

asyncpg = pytest.importorskip("asyncpg")


@pytest.mark.asyncio
async def test_database_migration_cycle():
    """alembic upgrade head -> downgrade -1 -> upgrade head must succeed on PostgreSQL."""
    pytest.skip("Implement with disposable PostgreSQL: run alembic cycle and assert paper_* tables exist/drop.")


@pytest.mark.asyncio
async def test_fill_transaction_is_atomic_and_rolls_back():
    pytest.skip("Implement with disposable PostgreSQL: inject fault before commit; assert zero rows persisted.")


@pytest.mark.asyncio
async def test_fill_retry_is_idempotent():
    pytest.skip("Implement with disposable PostgreSQL: re-submit same fill_id; assert single row, no double debit.")


@pytest.mark.asyncio
async def test_concurrent_fill_only_commits_once():
    pytest.skip("Implement with disposable PostgreSQL: two committers race on fill_id unique; exactly one wins.")


@pytest.mark.asyncio
async def test_processed_candle_db_dedup():
    pytest.skip("Implement with disposable PostgreSQL: two workers claim same candle key; one wins via unique.")


@pytest.mark.asyncio
async def test_two_sessions_are_durably_isolated():
    pytest.skip("Implement with disposable PostgreSQL: A and B rows never cross session_id boundary.")


@pytest.mark.asyncio
async def test_restart_restores_exact_state():
    pytest.skip("Implement with disposable PostgreSQL: snapshot before/after recovery are equal.")


@pytest.mark.asyncio
async def test_pnl_buckets_survive_restart():
    pytest.skip("Implement with disposable PostgreSQL: buckets read back identically after recovery.")
