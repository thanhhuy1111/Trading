"""Execution Engine and Exchange Simulator Schema Migration

Revision ID: 007_execution_engine_and_simulator
Revises: 006_risk_governor_and_orders
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '007_execution_engine_and_simulator'
down_revision: Union[str, None] = '006_risk_governor_and_orders'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Execution Plans Table
    op.create_table(
        'execution_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('approved_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tactic', sa.String(32), nullable=False),
        sa.Column('total_approved_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('maximum_notional', sa.Numeric(20, 8), nullable=False),
        sa.Column('maximum_entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('child_orders_json', postgresql.JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('plan_fingerprint', sa.String(64), nullable=False, unique=True)
    )

    # 2. Execution Records Table
    op.create_table(
        'execution_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('approved_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('current_status', sa.String(32), nullable=False),
        sa.Column('total_submitted_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('total_filled_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('cumulative_notional', sa.Numeric(20, 8), nullable=False),
        sa.Column('cumulative_fees', sa.Numeric(20, 8), nullable=False),
        sa.Column('average_fill_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 3. Exchange Orders Table (Simulator mode only)
    op.create_table(
        'exchange_orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exchange_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('approved_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('side', sa.String(16), nullable=False, server_default='BUY'),
        sa.Column('order_type', sa.String(32), nullable=False),
        sa.Column('time_in_force', sa.String(16), nullable=False),
        sa.Column('original_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('filled_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('remaining_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('limit_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('average_fill_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('cumulative_quote_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('cumulative_fee', sa.Numeric(20, 8), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('simulator_version', sa.String(16), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 4. Order State Transitions Table (Append-only)
    op.create_table(
        'order_state_transitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('previous_status', sa.String(32), nullable=False),
        sa.Column('new_status', sa.String(32), nullable=False),
        sa.Column('trigger', sa.String(64), nullable=False),
        sa.Column('reason_codes', postgresql.JSONB, nullable=False),
        sa.Column('actor', sa.String(64), nullable=False),
        sa.Column('transitioned_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 5. Fills Table
    op.create_table(
        'fills',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('fill_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('exchange_fill_id', sa.String(64), nullable=False),
        sa.Column('exchange_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('side', sa.String(16), nullable=False, server_default='BUY'),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('price', sa.Numeric(20, 8), nullable=False),
        sa.Column('quote_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('fee', sa.Numeric(20, 8), nullable=False),
        sa.Column('fee_asset', sa.String(16), nullable=False, server_default='USDT'),
        sa.Column('liquidity', sa.String(16), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('market_data_reference_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('simulator_version', sa.String(16), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.UniqueConstraint('exchange_order_id', 'exchange_fill_id', name='uq_exchange_order_fill_id')
    )

    # 6. Execution Reports Table
    op.create_table(
        'execution_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('report_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('approved_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('final_status', sa.String(32), nullable=False),
        sa.Column('approved_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('submitted_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('filled_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('unfilled_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('maximum_notional', sa.Numeric(20, 8), nullable=False),
        sa.Column('executed_notional', sa.Numeric(20, 8), nullable=False),
        sa.Column('total_fee', sa.Numeric(20, 8), nullable=False),
        sa.Column('average_fill_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('maximum_entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('child_order_ids', postgresql.JSONB, nullable=False),
        sa.Column('fill_ids', postgresql.JSONB, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('execution_policy_version', sa.String(16), nullable=False),
        sa.Column('simulator_version', sa.String(16), nullable=False),
        sa.Column('report_fingerprint', sa.String(64), nullable=False, unique=True),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1')
    )

    # 7. Execution Incidents Table
    op.create_table(
        'execution_incidents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('incident_type', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_table('execution_incidents')
    op.drop_table('execution_reports')
    op.drop_table('fills')
    op.drop_table('order_state_transitions')
    op.drop_table('exchange_orders')
    op.drop_table('execution_records')
    op.drop_table('execution_plans')
