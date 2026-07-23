"""Round 3: Durable paper-trading runtime persistence (F-02/F-03/F-04/F-05)

Adds session-scoped durable state for paper trading: processed-candle claims (DB dedup),
orders, fills, ledger entries, positions, realized-PnL buckets, and risk state. These live in a
dedicated ``paper_*`` namespace to avoid colliding with the earlier (non-session-scoped)
execution/ledger tables from migrations 007/008. Mirrors packages/persistence/schema.py.

Revision ID: 013_paper_runtime_persistence
Revises: 012_security_hardening
Create Date: 2026-07-23

NOTE: NOT executed against PostgreSQL in the build environment (no server available). The
upgrade/downgrade cycle must be run on a disposable Postgres before this is considered verified.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013_paper_runtime_persistence"
down_revision = "012_security_hardening"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NUM = sa.Numeric(precision=20, scale=8)
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "paper_processed_candles",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("session_id", _UUID, sa.ForeignKey("paper_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("open_time", _TS, nullable=False),
        sa.Column("close_time", _TS, nullable=False),
        sa.Column("event_time", _TS, nullable=False),
        sa.Column("source", sa.String(100), nullable=False, server_default="public_stream"),
        sa.Column("payload_checksum", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(30), nullable=False, server_default="RECEIVED"),
        sa.Column("decision_id", _UUID, nullable=True),
        sa.Column("claimed_at", _TS, nullable=True),
        sa.Column("completed_at", _TS, nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "symbol", "timeframe", "close_time", name="uq_paper_candle_key"),
    )
    op.create_index("ix_paper_candles_session_close", "paper_processed_candles", ["session_id", "close_time"])

    op.create_table(
        "paper_orders",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("session_id", _UUID, sa.ForeignKey("paper_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_order_id", _UUID, nullable=False),
        sa.Column("approved_order_id", _UUID, nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", _NUM, nullable=False),
        sa.Column("limit_price", _NUM, nullable=False),
        sa.Column("maximum_entry_price", _NUM, nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING_EXECUTION"),
        sa.Column("filled_quantity", _NUM, nullable=False, server_default="0"),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "client_order_id", name="uq_paper_order_client_id"),
    )
    op.create_index("ix_paper_orders_session_created", "paper_orders", ["session_id", "created_at"])

    op.create_table(
        "paper_fills",
        sa.Column("fill_id", _UUID, primary_key=True),
        sa.Column("session_id", _UUID, sa.ForeignKey("paper_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_order_id", _UUID, nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", _NUM, nullable=False),
        sa.Column("price", _NUM, nullable=False),
        sa.Column("quote_quantity", _NUM, nullable=False),
        sa.Column("fee", _NUM, nullable=False, server_default="0"),
        sa.Column("fee_asset", sa.String(20), nullable=False, server_default="USDT"),
        sa.Column("event_time", _TS, nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_paper_fills_session_event", "paper_fills", ["session_id", "event_time"])

    op.create_table(
        "paper_ledger_entries",
        sa.Column("entry_id", _UUID, primary_key=True),
        sa.Column("session_id", _UUID, sa.ForeignKey("paper_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("fill_id", _UUID, sa.ForeignKey("paper_fills.fill_id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset", sa.String(20), nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("amount", _NUM, nullable=False),
        sa.Column("currency", sa.String(20), nullable=False, server_default="USDT"),
        sa.Column("event_time", _TS, nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_paper_ledger_session_event", "paper_ledger_entries", ["session_id", "event_time"])

    op.create_table(
        "paper_positions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("session_id", _UUID, sa.ForeignKey("paper_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("quantity", _NUM, nullable=False, server_default="0"),
        sa.Column("average_entry_price", _NUM, nullable=False, server_default="0"),
        sa.Column("total_cost_basis", _NUM, nullable=False, server_default="0"),
        sa.Column("realized_pnl", _NUM, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "symbol", name="uq_paper_position_session_symbol"),
    )
    op.create_index("ix_paper_positions_session_symbol", "paper_positions", ["session_id", "symbol"])

    op.create_table(
        "paper_pnl_buckets",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("session_id", _UUID, sa.ForeignKey("paper_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("bucket_type", sa.String(10), nullable=False),
        sa.Column("bucket_start", _TS, nullable=False),
        sa.Column("bucket_end", _TS, nullable=False),
        sa.Column("realized_pnl", _NUM, nullable=False, server_default="0"),
        sa.Column("fees", _NUM, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "bucket_type", "bucket_start", name="uq_paper_pnl_bucket"),
    )
    op.create_index("ix_paper_pnl_buckets_key", "paper_pnl_buckets", ["session_id", "bucket_type", "bucket_start"])

    op.create_table(
        "paper_risk_states",
        sa.Column("session_id", _UUID, sa.ForeignKey("paper_sessions.session_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("equity_peak", _NUM, nullable=False),
        sa.Column("current_drawdown_pct", _NUM, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_index("ix_paper_pnl_buckets_key", table_name="paper_pnl_buckets")
    op.drop_table("paper_risk_states")
    op.drop_table("paper_pnl_buckets")
    op.drop_index("ix_paper_positions_session_symbol", table_name="paper_positions")
    op.drop_table("paper_positions")
    op.drop_index("ix_paper_ledger_session_event", table_name="paper_ledger_entries")
    op.drop_table("paper_ledger_entries")
    op.drop_index("ix_paper_fills_session_event", table_name="paper_fills")
    op.drop_table("paper_fills")
    op.drop_index("ix_paper_orders_session_created", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_candles_session_close", table_name="paper_processed_candles")
    op.drop_table("paper_processed_candles")
