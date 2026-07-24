"""SQLAlchemy Core table definitions for durable paper-trading runtime state.

These mirror Alembic migration ``013_paper_runtime_persistence`` exactly. They exist so the
schema can be design-verified without a live database (DDL compiles for the postgresql dialect;
unique constraints / indexes are introspectable). They live in a dedicated ``paper_*`` namespace
to avoid colliding with the earlier execution/ledger tables (migrations 007/008), which are not
session-scoped for paper trading.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

_UUID = postgresql.UUID(as_uuid=True)
_NUM = sa.Numeric(precision=20, scale=8)
_TS = sa.DateTime(timezone=True)

# One row per accepted closed candle — the DB-backed dedup / processing claim (F-02).
paper_processed_candles = sa.Table(
    "paper_processed_candles",
    metadata,
    sa.Column("id", _UUID, primary_key=True),
    sa.Column("session_id", _UUID, nullable=False),
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
    sa.Index("ix_paper_candles_session_close", "session_id", "close_time"),
)

# Session-scoped order (F-03/F-04). Idempotent by (session_id, client_order_id).
paper_orders = sa.Table(
    "paper_orders",
    metadata,
    sa.Column("id", _UUID, primary_key=True),
    sa.Column("session_id", _UUID, nullable=False),
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
    sa.Index("ix_paper_orders_session_created", "session_id", "created_at"),
)

# Session-scoped fill. fill_id is globally unique — the last-resort idempotency guard (F-04).
paper_fills = sa.Table(
    "paper_fills",
    metadata,
    sa.Column("fill_id", _UUID, primary_key=True),
    sa.Column("session_id", _UUID, nullable=False),
    sa.Column("sequence_number", sa.BigInteger(), sa.Identity(), nullable=False),
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
    sa.Index("ix_paper_fills_session_event", "session_id", "event_time"),
)

# Append-only double-entry ledger (F-03/F-04).
paper_ledger_entries = sa.Table(
    "paper_ledger_entries",
    metadata,
    sa.Column("entry_id", _UUID, primary_key=True),
    sa.Column("session_id", _UUID, nullable=False),
    sa.Column("fill_id", _UUID, sa.ForeignKey("paper_fills.fill_id", ondelete="CASCADE"), nullable=False),
    sa.Column("asset", sa.String(20), nullable=False),
    sa.Column("entry_type", sa.String(20), nullable=False),
    sa.Column("amount", _NUM, nullable=False),
    sa.Column("currency", sa.String(20), nullable=False, server_default="USDT"),
    sa.Column("event_time", _TS, nullable=False),
    sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
    sa.Index("ix_paper_ledger_session_event", "session_id", "event_time"),
)

# Materialized per-session position with optimistic version (F-03).
paper_positions = sa.Table(
    "paper_positions",
    metadata,
    sa.Column("id", _UUID, primary_key=True),
    sa.Column("session_id", _UUID, nullable=False),
    sa.Column("symbol", sa.String(50), nullable=False),
    sa.Column("quantity", _NUM, nullable=False, server_default="0"),
    sa.Column("average_entry_price", _NUM, nullable=False, server_default="0"),
    sa.Column("total_cost_basis", _NUM, nullable=False, server_default="0"),
    sa.Column("realized_pnl", _NUM, nullable=False, server_default="0"),
    sa.Column("total_fees", _NUM, nullable=False, server_default="0"),
    sa.Column("initial_stop_price", _NUM, nullable=True),
    sa.Column("active_stop_price", _NUM, nullable=True),
    sa.Column("take_profit_price", _NUM, nullable=True),
    sa.Column("trailing_stop_price", _NUM, nullable=True),
    sa.Column("current_market_price", _NUM, nullable=True),
    sa.Column("market_value", _NUM, nullable=True),
    sa.Column("opened_at", _TS, nullable=True),
    sa.Column("last_fill_at", _TS, nullable=True),
    sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
    sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint("session_id", "symbol", name="uq_paper_position_session_symbol"),
    sa.Index("ix_paper_positions_session_symbol", "session_id", "symbol"),
)

# Durable UTC-day / ISO-week realized PnL buckets (F-05).
paper_pnl_buckets = sa.Table(
    "paper_pnl_buckets",
    metadata,
    sa.Column("id", _UUID, primary_key=True),
    sa.Column("session_id", _UUID, nullable=False),
    sa.Column("bucket_type", sa.String(10), nullable=False),
    sa.Column("bucket_start", _TS, nullable=False),
    sa.Column("bucket_end", _TS, nullable=False),
    sa.Column("realized_pnl", _NUM, nullable=False, server_default="0"),
    sa.Column("fees", _NUM, nullable=False, server_default="0"),
    sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint("session_id", "bucket_type", "bucket_start", name="uq_paper_pnl_bucket"),
    sa.Index("ix_paper_pnl_buckets_key", "session_id", "bucket_type", "bucket_start"),
)

# Per-session risk state snapshot (F-04 recovery target).
paper_risk_states = sa.Table(
    "paper_risk_states",
    metadata,
    sa.Column("session_id", _UUID, primary_key=True),
    sa.Column("state", sa.String(20), nullable=False, server_default="NORMAL"),
    sa.Column("equity_peak", _NUM, nullable=False),
    sa.Column("current_drawdown_pct", _NUM, nullable=False, server_default="0"),
    sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
)

ALL_TABLES = [
    paper_processed_candles,
    paper_orders,
    paper_fills,
    paper_ledger_entries,
    paper_positions,
    paper_pnl_buckets,
    paper_risk_states,
]
