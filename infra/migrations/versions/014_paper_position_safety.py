"""Persist paper position protection and accounting state.

Revision ID: 014_paper_position_safety
Revises: 013_paper_runtime_persistence
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op

revision = "014_paper_position_safety"
down_revision = "013_paper_runtime_persistence"
branch_labels = None
depends_on = None

_NUM = sa.Numeric(precision=20, scale=8)
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "paper_fills",
        sa.Column("sequence_number", sa.BigInteger(), sa.Identity(), nullable=False),
    )
    op.add_column("paper_positions", sa.Column("total_fees", _NUM, nullable=False, server_default="0"))
    op.add_column("paper_positions", sa.Column("initial_stop_price", _NUM, nullable=True))
    op.add_column("paper_positions", sa.Column("active_stop_price", _NUM, nullable=True))
    op.add_column("paper_positions", sa.Column("take_profit_price", _NUM, nullable=True))
    op.add_column("paper_positions", sa.Column("trailing_stop_price", _NUM, nullable=True))
    op.add_column("paper_positions", sa.Column("current_market_price", _NUM, nullable=True))
    op.add_column("paper_positions", sa.Column("market_value", _NUM, nullable=True))
    op.add_column("paper_positions", sa.Column("opened_at", _TS, nullable=True))
    op.add_column("paper_positions", sa.Column("last_fill_at", _TS, nullable=True))


def downgrade() -> None:
    for column in (
        "last_fill_at",
        "opened_at",
        "market_value",
        "current_market_price",
        "trailing_stop_price",
        "take_profit_price",
        "active_stop_price",
        "initial_stop_price",
        "total_fees",
    ):
        op.drop_column("paper_positions", column)
    op.drop_column("paper_fills", "sequence_number")
