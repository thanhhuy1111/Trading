"""Position Manager and Portfolio Ledger Schema Migration

Revision ID: 008_position_manager_and_ledger
Revises: 007_execution_engine_and_simulator
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '008_position_manager_and_ledger'
down_revision: Union[str, None] = '007_execution_engine_and_simulator'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Trading Accounts Table
    op.create_table(
        'trading_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', sa.String(64), nullable=False, unique=True),
        sa.Column('base_currency', sa.String(16), nullable=False, server_default='USDT'),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('accounting_method', sa.String(32), nullable=False, server_default='WEIGHTED_AVERAGE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 2. Ledger Transactions Table
    op.create_table(
        'ledger_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('transaction_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('transaction_type', sa.String(32), nullable=False),
        sa.Column('reference_type', sa.String(64), nullable=False),
        sa.Column('reference_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False, unique=True)
    )

    # 3. Ledger Entries Table (Append-only)
    op.create_table(
        'ledger_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entry_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('transaction_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('asset', sa.String(16), nullable=False),
        sa.Column('entry_type', sa.String(32), nullable=False),
        sa.Column('amount', sa.Numeric(20, 8), nullable=False),
        sa.Column('fill_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reference_type', sa.String(64), nullable=False),
        sa.Column('reference_id', sa.String(64), nullable=False),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sequence_number', sa.BigInteger, nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 4. Asset Balances Table
    op.create_table(
        'asset_balances',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('asset', sa.String(16), nullable=False),
        sa.Column('total_balance', sa.Numeric(20, 8), nullable=False),
        sa.Column('available_balance', sa.Numeric(20, 8), nullable=False),
        sa.Column('reserved_balance', sa.Numeric(20, 8), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('account_id', 'asset', name='uq_account_asset')
    )

    # 5. Positions Table
    op.create_table(
        'positions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('side', sa.String(16), nullable=False, server_default='LONG'),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('available_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('reserved_exit_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('average_entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('total_cost_basis', sa.Numeric(20, 8), nullable=False),
        sa.Column('realized_pnl', sa.Numeric(20, 8), nullable=False),
        sa.Column('unrealized_pnl', sa.Numeric(20, 8), nullable=False),
        sa.Column('total_fees', sa.Numeric(20, 8), nullable=False),
        sa.Column('current_market_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('market_value', sa.Numeric(20, 8), nullable=True),
        sa.Column('initial_stop_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('active_stop_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('take_profit_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('trailing_stop_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_fill_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 6. Position Events Table
    op.create_table(
        'position_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('payload_json', postgresql.JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 7. Processed Fills Table
    op.create_table(
        'processed_fills',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('fill_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('account_id', 'fill_id', name='uq_account_fill_id')
    )

    # 8. Realized PnL Entries Table
    op.create_table(
        'realized_pnl_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('pnl_entry_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sell_fill_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('sale_proceeds', sa.Numeric(20, 8), nullable=False),
        sa.Column('released_cost_basis', sa.Numeric(20, 8), nullable=False),
        sa.Column('exit_fee', sa.Numeric(20, 8), nullable=False),
        sa.Column('realized_pnl', sa.Numeric(20, 8), nullable=False),
        sa.Column('realized_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accounting_method', sa.String(32), nullable=False, server_default='WEIGHTED_AVERAGE'),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 9. Portfolio Snapshots Table
    op.create_table(
        'portfolio_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('cash_balance', sa.Numeric(20, 8), nullable=False),
        sa.Column('available_cash', sa.Numeric(20, 8), nullable=False),
        sa.Column('asset_market_value', sa.Numeric(20, 8), nullable=False),
        sa.Column('nav', sa.Numeric(20, 8), nullable=False),
        sa.Column('gross_exposure', sa.Numeric(20, 8), nullable=False),
        sa.Column('net_exposure', sa.Numeric(20, 8), nullable=False),
        sa.Column('open_risk_amount', sa.Numeric(20, 8), nullable=False),
        sa.Column('realized_pnl_today', sa.Numeric(20, 8), nullable=False),
        sa.Column('realized_pnl_week', sa.Numeric(20, 8), nullable=False),
        sa.Column('unrealized_pnl', sa.Numeric(20, 8), nullable=False),
        sa.Column('total_fees', sa.Numeric(20, 8), nullable=False),
        sa.Column('equity_peak', sa.Numeric(20, 8), nullable=False),
        sa.Column('drawdown_pct', sa.Numeric(20, 8), nullable=False),
        sa.Column('positions_json', postgresql.JSONB, nullable=False),
        sa.Column('valuation_quality', sa.String(32), nullable=False),
        sa.Column('data_as_of', sa.DateTime(timezone=True), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 10. Equity Peak History Table
    op.create_table(
        'equity_peak_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('equity_peak', sa.Numeric(20, 8), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 11. Position Exit Intents Table
    op.create_table(
        'position_exit_intents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exit_intent_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('side', sa.String(16), nullable=False, server_default='SELL'),
        sa.Column('reduce_only', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('requested_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('maximum_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('trigger_type', sa.String(32), nullable=False),
        sa.Column('trigger_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('reference_market_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('minimum_exit_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('maximum_slippage_bps', sa.Numeric(20, 8), nullable=False),
        sa.Column('position_version', sa.Integer, nullable=False),
        sa.Column('market_data_reference_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING_RISK_REVIEW'),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 12. Approved Exit Orders Table
    op.create_table(
        'approved_exit_orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('approved_exit_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('exit_intent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('side', sa.String(16), nullable=False, server_default='SELL'),
        sa.Column('reduce_only', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('approved_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('minimum_exit_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('maximum_slippage_bps', sa.Numeric(20, 8), nullable=False),
        sa.Column('position_version', sa.Integer, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('governor_version', sa.String(16), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING_EXECUTION'),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 13. Exit Quantity Reservations Table
    op.create_table(
        'exit_quantity_reservations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('approved_exit_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reserved_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('remaining_reserved_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )


def downgrade() -> None:
    op.drop_table('exit_quantity_reservations')
    op.drop_table('approved_exit_orders')
    op.drop_table('position_exit_intents')
    op.drop_table('equity_peak_history')
    op.drop_table('portfolio_snapshots')
    op.drop_table('realized_pnl_entries')
    op.drop_table('processed_fills')
    op.drop_table('position_events')
    op.drop_table('positions')
    op.drop_table('asset_balances')
    op.drop_table('ledger_entries')
    op.drop_table('ledger_transactions')
    op.drop_table('trading_accounts')
