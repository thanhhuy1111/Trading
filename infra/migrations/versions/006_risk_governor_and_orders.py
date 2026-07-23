"""Risk Governor and Approved Orders Schema Migration

Revision ID: 006_risk_governor_and_orders
Revises: 005_governance_and_intents
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '006_risk_governor_and_orders'
down_revision: Union[str, None] = '005_governance_and_intents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Risk Policies Table
    op.create_table(
        'risk_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('version', sa.String(16), nullable=False, unique=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='ACTIVE'),
        sa.Column('config_json', postgresql.JSONB, nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 2. Risk State History Table
    op.create_table(
        'risk_state_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('previous_state', sa.String(32), nullable=False),
        sa.Column('new_state', sa.String(32), nullable=False),
        sa.Column('trigger', sa.String(64), nullable=False),
        sa.Column('reason_codes', postgresql.JSONB, nullable=False),
        sa.Column('portfolio_snapshot_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('changed_by', sa.String(64), nullable=False)
    )

    # 3. Risk Decisions Table
    op.create_table(
        'risk_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('decision_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('result', sa.String(32), nullable=False),
        sa.Column('risk_state', sa.String(32), nullable=False),
        sa.Column('nav', sa.Numeric(20, 8), nullable=False),
        sa.Column('base_risk_budget', sa.Numeric(20, 8), nullable=False),
        sa.Column('adjusted_risk_budget', sa.Numeric(20, 8), nullable=False),
        sa.Column('reference_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('conservative_entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('approved_stop_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('raw_quantity', sa.Numeric(20, 8), nullable=True),
        sa.Column('approved_quantity', sa.Numeric(20, 8), nullable=True),
        sa.Column('approved_notional', sa.Numeric(20, 8), nullable=True),
        sa.Column('actual_risk_amount', sa.Numeric(20, 8), nullable=True),
        sa.Column('actual_risk_pct', sa.Numeric(8, 4), nullable=True),
        sa.Column('current_open_risk_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('projected_open_risk_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('current_total_exposure_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('projected_total_exposure_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('projected_symbol_allocation_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('projected_correlated_exposure_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('daily_loss_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('weekly_loss_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('drawdown_pct', sa.Numeric(8, 4), nullable=False),
        sa.Column('checks_json', postgresql.JSONB, nullable=False),
        sa.Column('warning_codes', postgresql.JSONB, nullable=False),
        sa.Column('rejection_codes', postgresql.JSONB, nullable=False),
        sa.Column('portfolio_snapshot_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('symbol_metadata_version', sa.String(16), nullable=False),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('governor_version', sa.String(16), nullable=False),
        sa.Column('decision_fingerprint', sa.String(64), nullable=False, unique=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 4. Approved Orders Table (NO exchange order ID, status=PENDING_EXECUTION)
    op.create_table(
        'approved_orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('approved_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('client_order_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('risk_decision_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('side', sa.String(16), nullable=False, server_default='BUY'),
        sa.Column('approved_quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('maximum_notional', sa.Numeric(20, 8), nullable=False),
        sa.Column('approved_stop_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('maximum_entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('maximum_entry_slippage_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('risk_policy_version', sa.String(16), nullable=False),
        sa.Column('governor_version', sa.String(16), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING_EXECUTION'),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_approved_orders_lookup', 'approved_orders', ['symbol', 'status', 'created_at'])

    # 5. Risk Limit Breaches Table
    op.create_table(
        'risk_limit_breaches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('limit_type', sa.String(64), nullable=False),
        sa.Column('current_value', sa.Numeric(20, 8), nullable=False),
        sa.Column('threshold_value', sa.Numeric(20, 8), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_table('risk_limit_breaches')
    op.drop_index('ix_approved_orders_lookup', table_name='approved_orders')
    op.drop_table('approved_orders')
    op.drop_table('risk_decisions')
    op.drop_table('risk_state_history')
    op.drop_table('risk_policies')
