"""Market Data Platform Schema Migration

Revision ID: 003_market_data
Revises: 002_event_bus_and_config
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '003_market_data'
down_revision: Union[str, None] = '002_event_bus_and_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Exchanges Table
    op.create_table(
        'exchanges',
        sa.Column('exchange_id', sa.String(32), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('rate_limits', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )

    # 2. Symbols Table
    op.create_table(
        'symbols',
        sa.Column('canonical_symbol', sa.String(32), primary_key=True),
        sa.Column('exchange_symbol', sa.String(32), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('base_asset', sa.String(16), nullable=False),
        sa.Column('quote_asset', sa.String(16), nullable=False),
        sa.Column('price_tick_size', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('quantity_step_size', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('min_quantity', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('min_notional', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, default='TRADING'),
        sa.Column('trading_permissions', postgresql.JSONB(), server_default='["SPOT"]'),
        sa.Column('metadata_version', sa.Integer(), nullable=False, default=1),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )

    # 3. Candles Table
    op.create_table(
        'candles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(16), nullable=False),
        sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('close_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open_price', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('high_price', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('low_price', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('close_price', sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column('volume', sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column('quote_volume', sa.Numeric(precision=24, scale=8), nullable=False, default=0),
        sa.Column('trades_count', sa.Integer(), nullable=False, default=0),
        sa.Column('is_closed', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('exchange', 'symbol', 'timeframe', 'open_time', name='uq_candles_exch_sym_tf_open')
    )
    op.create_index('idx_candles_query', 'candles', ['symbol', 'timeframe', 'open_time'])

    # 4. Ingestion Jobs Table
    op.create_table(
        'ingestion_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(16), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, default='PENDING'),
        sa.Column('processed_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 5. Ingestion Checkpoints Table
    op.create_table(
        'ingestion_checkpoints',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(16), nullable=False),
        sa.Column('last_ingested_open_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('exchange', 'symbol', 'timeframe', name='uq_checkpoints_exch_sym_tf')
    )

    # 6. Market Data Health Table
    op.create_table(
        'market_data_health',
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('trades_status', sa.String(32), nullable=False, default='HEALTHY'),
        sa.Column('candles_status', sa.String(32), nullable=False, default='HEALTHY'),
        sa.Column('order_book_status', sa.String(32), nullable=False, default='HEALTHY'),
        sa.Column('overall_status', sa.String(32), nullable=False, default='HEALTHY'),
        sa.Column('last_trade_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_candle_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_order_book_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('exchange', 'symbol', name='pk_market_data_health')
    )

    # 7. Data Quality Issues Table
    op.create_table(
        'data_quality_issues',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('data_type', sa.String(32), nullable=False),
        sa.Column('issue_code', sa.String(64), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(32), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('is_resolved', sa.Boolean(), nullable=False, default=False)
    )

    # 8. Data Corrections Table
    op.create_table(
        'data_corrections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(16), nullable=False),
        sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('previous_value', postgresql.JSONB(), nullable=False),
        sa.Column('new_value', postgresql.JSONB(), nullable=False),
        sa.Column('source', sa.String(64), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )

    # 9. WebSocket Connections Table
    op.create_table(
        'websocket_connections',
        sa.Column('connection_id', sa.String(64), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('reconnect_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )


def downgrade() -> None:
    op.drop_table('websocket_connections')
    op.drop_table('data_corrections')
    op.drop_table('data_quality_issues')
    op.drop_table('market_data_health')
    op.drop_table('ingestion_checkpoints')
    op.drop_table('ingestion_jobs')
    op.drop_index('idx_candles_query', table_name='candles')
    op.drop_table('candles')
    op.drop_table('symbols')
    op.drop_table('exchanges')
