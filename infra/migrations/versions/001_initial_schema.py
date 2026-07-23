"""Initial Database Schema Migration

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Exchanges
    op.create_table(
        'exchanges',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('is_testnet', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 2. Symbols
    op.create_table(
        'symbols',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('base_asset', sa.String(32), nullable=False),
        sa.Column('quote_asset', sa.String(32), nullable=False),
        sa.Column('price_precision', sa.Integer(), default=2),
        sa.Column('quantity_precision', sa.Integer(), default=6),
        sa.Column('min_notional', sa.Numeric(18, 8), default=10.0),
        sa.Column('is_active', sa.Boolean(), default=True)
    )

    # 3. Trade Intents
    op.create_table(
        'trade_intents',
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('symbol', sa.String(64), nullable=False),
        sa.Column('side', sa.String(16), nullable=False),
        sa.Column('expected_return_bps', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('entry_price_reference', sa.Numeric(18, 8), nullable=False),
        sa.Column('stop_price', sa.Numeric(18, 8), nullable=False),
        sa.Column('take_profit_price', sa.Numeric(18, 8), nullable=False),
        sa.Column('feature_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 4. Risk Decisions
    op.create_table(
        'risk_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('approved_quantity', sa.Numeric(18, 8), nullable=False),
        sa.Column('approved_notional', sa.Numeric(18, 8), nullable=False),
        sa.Column('risk_amount', sa.Numeric(18, 8), nullable=False),
        sa.Column('risk_percentage', sa.Float(), nullable=False),
        sa.Column('rejection_codes', postgresql.JSONB(), server_default='[]'),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 5. Orders
    op.create_table(
        'orders',
        sa.Column('client_order_id', sa.String(128), primary_key=True),
        sa.Column('exchange_order_id', sa.String(128), nullable=True),
        sa.Column('symbol', sa.String(64), nullable=False),
        sa.Column('side', sa.String(16), nullable=False),
        sa.Column('order_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('price', sa.Numeric(18, 8), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 8), nullable=False),
        sa.Column('executed_quantity', sa.Numeric(18, 8), default=0.0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 6. Fills
    op.create_table(
        'fills',
        sa.Column('fill_id', sa.String(128), primary_key=True),
        sa.Column(
            'client_order_id',
            sa.String(128),
            sa.ForeignKey('orders.client_order_id'),
            nullable=False
        ),
        sa.Column('symbol', sa.String(64), nullable=False),
        sa.Column('price', sa.Numeric(18, 8), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 8), nullable=False),
        sa.Column('fee', sa.Numeric(18, 8), default=0.0),
        sa.Column('fee_asset', sa.String(32), default='USDT'),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 7. Positions
    op.create_table(
        'positions',
        sa.Column('position_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('symbol', sa.String(64), nullable=False),
        sa.Column('side', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 8), nullable=False),
        sa.Column('entry_price', sa.Numeric(18, 8), nullable=False),
        sa.Column('current_stop', sa.Numeric(18, 8), nullable=False),
        sa.Column('take_profit', sa.Numeric(18, 8), nullable=False),
        sa.Column('unrealized_pnl', sa.Numeric(18, 8), default=0.0),
        sa.Column('realized_pnl', sa.Numeric(18, 8), default=0.0),
        sa.Column('is_open', sa.Boolean(), default=True),
        sa.Column('exit_reason', sa.String(64), nullable=True),
        sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 8. Portfolio Snapshots
    op.create_table(
        'portfolio_snapshots',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('total_nav', sa.Numeric(18, 8), nullable=False),
        sa.Column('cash_balance', sa.Numeric(18, 8), nullable=False),
        sa.Column('unrealized_pnl', sa.Numeric(18, 8), nullable=False),
        sa.Column('current_drawdown_pct', sa.Float(), nullable=False),
        sa.Column('open_positions_count', sa.Integer(), nullable=False)
    )

    # 9. Incidents
    op.create_table(
        'incidents',
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('severity', sa.String(32), nullable=False),
        sa.Column('service_name', sa.String(64), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details', postgresql.JSONB(), server_default='{}'),
        sa.Column('is_acknowledged', sa.Boolean(), default=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 10. Audit Log (Append-Only)
    op.create_table(
        'audit_events',
        sa.Column('event_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('service_name', sa.String(64), nullable=False),
        sa.Column('actor', sa.String(64), default='system'),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('payload', postgresql.JSONB(), server_default='{}')
    )


def downgrade() -> None:
    op.drop_table('audit_events')
    op.drop_table('incidents')
    op.drop_table('portfolio_snapshots')
    op.drop_table('positions')
    op.drop_table('fills')
    op.drop_table('orders')
    op.drop_table('risk_decisions')
    op.drop_table('trade_intents')
    op.drop_table('symbols')
    op.drop_table('exchanges')
