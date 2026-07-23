"""F-04 atomicity + idempotency LOGIC (verified with a fake transaction, no DB).

These tests verify the orchestration contract only: step ordering, rollback-on-failure (no
partial commit), and duplicate -> idempotent (no double mutation). They do NOT verify durability
on PostgreSQL.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from packages.persistence.unit_of_work import FILL_COMMIT_STEP_ORDER, FillCommitOrchestrator


@dataclass
class _Fill:
    fill_id: UUID


class _FakeOps:
    def __init__(self, *, already=False, fail_at=None, integrity_on_insert=False):
        self.already = already
        self.fail_at = fail_at
        self.integrity_on_insert = integrity_on_insert
        self.calls: list[str] = []
        self.committed = False
        self.rolled_back = False

    async def _step(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(f"injected failure at {name}")

    async def fill_already_committed(self, fill_id):
        return self.already

    async def insert_fill(self, fill):
        self.calls.append("insert_fill")
        if self.integrity_on_insert:
            raise IntegrityError("insert", {}, Exception("duplicate key"))
        if self.fail_at == "insert_fill":
            raise RuntimeError("injected failure at insert_fill")

    async def insert_ledger_entries(self, fill): await self._step("insert_ledger_entries")
    async def upsert_position(self, fill): await self._step("upsert_position")
    async def update_pnl_bucket(self, fill, realized_pnl): await self._step("update_pnl_bucket")
    async def update_risk_state(self, fill): await self._step("update_risk_state")
    async def append_journal(self, fill): await self._step("append_journal")
    async def mark_order_filled(self, fill): await self._step("mark_order_filled")

    async def commit(self):
        self.calls.append("commit")
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


_orch = FillCommitOrchestrator()


def test_happy_path_runs_all_steps_in_order_and_commits() -> None:
    ops = _FakeOps()
    res = asyncio.run(_orch.commit_fill(ops, _Fill(uuid4()), realized_pnl=Decimal("0")))
    assert res.committed is True
    assert res.idempotent_replay is False
    assert ops.committed is True
    assert ops.rolled_back is False
    assert ops.calls == FILL_COMMIT_STEP_ORDER  # exact mandated order incl. commit


def test_fast_path_idempotent_when_already_committed() -> None:
    ops = _FakeOps(already=True)
    res = asyncio.run(_orch.commit_fill(ops, _Fill(uuid4())))
    assert res.idempotent_replay is True
    assert res.committed is False
    assert ops.committed is False
    assert "insert_fill" not in ops.calls  # no mutation attempted


def test_failure_midway_rolls_back_and_does_not_commit() -> None:
    ops = _FakeOps(fail_at="upsert_position")
    with pytest.raises(RuntimeError):
        asyncio.run(_orch.commit_fill(ops, _Fill(uuid4())))
    assert ops.committed is False       # NO partial commit
    assert ops.rolled_back is True
    assert "commit" not in ops.calls
    assert "update_pnl_bucket" not in ops.calls  # stopped at the failing step


def test_duplicate_fill_integrity_error_is_idempotent_not_double_commit() -> None:
    ops = _FakeOps(integrity_on_insert=True)
    res = asyncio.run(_orch.commit_fill(ops, _Fill(uuid4())))
    assert res.idempotent_replay is True
    assert res.committed is False
    assert ops.committed is False       # unique constraint prevented a second commit
    assert ops.rolled_back is True
