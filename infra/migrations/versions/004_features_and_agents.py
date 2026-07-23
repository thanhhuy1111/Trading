"""Feature Engine and Strategy Agents Schema Migration

Revision ID: 004_features_and_agents
Revises: 003_market_data
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '004_features_and_agents'
down_revision: Union[str, None] = '003_market_data'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Feature Definitions Table
    op.create_table(
        'feature_definitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('version', sa.String(16), nullable=False),
        sa.Column('category', sa.String(32), nullable=False),
        sa.Column('feature_metadata', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('name', 'version', name='uq_feature_def_name_version')
    )

    # 2. Feature Sets Table
    op.create_table(
        'feature_sets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('version', sa.String(16), nullable=False),
        sa.Column('definitions', postgresql.JSONB, nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('name', 'version', name='uq_feature_set_name_version')
    )

    # 3. Feature Snapshots Table
    op.create_table(
        'feature_snapshots',
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(16), nullable=False),
        sa.Column('feature_set', sa.String(64), nullable=False),
        sa.Column('feature_set_version', sa.String(16), nullable=False),
        sa.Column('event_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('as_of_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lookback_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lookback_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('values', postgresql.JSONB, nullable=False),
        sa.Column('quality_status', sa.String(32), nullable=False),
        sa.Column('quality_issues', postgresql.JSONB, nullable=False),
        sa.Column('source_data_version', sa.String(32), nullable=False),
        sa.Column('lineage', postgresql.JSONB, nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            'exchange', 'symbol', 'timeframe', 'feature_set', 'feature_set_version', 'as_of_time',
            name='uq_feature_snapshot_key'
        )
    )
    op.create_index(
        'ix_feature_snapshots_lookup', 'feature_snapshots', ['exchange', 'symbol', 'timeframe', 'as_of_time']
    )

    # 4. Agent Definitions Table
    op.create_table(
        'agent_definitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(64), nullable=False, unique=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('version', sa.String(16), nullable=False),
        sa.Column('strategy_type', sa.String(32), nullable=False),
        sa.Column('required_feature_set', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='ACTIVE'),
        sa.Column('agent_metadata', postgresql.JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 5. Agent Signals Table
    op.create_table(
        'agent_signals',
        sa.Column('signal_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', sa.String(64), nullable=False),
        sa.Column('agent_name', sa.String(64), nullable=False),
        sa.Column('agent_version', sa.String(16), nullable=False),
        sa.Column('strategy_type', sa.String(32), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('timeframe', sa.String(16), nullable=False),
        sa.Column('action', sa.String(32), nullable=False),
        sa.Column('expected_return_bps', sa.Numeric(12, 4), nullable=True),
        sa.Column('confidence', sa.Numeric(6, 4), nullable=False),
        sa.Column('horizon_minutes', sa.Integer, nullable=False),
        sa.Column('reference_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('invalidation_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('suggested_stop_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('suggested_take_profit_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('market_regime', sa.String(32), nullable=False),
        sa.Column('feature_snapshot_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feature_set_version', sa.String(16), nullable=False),
        sa.Column('feature_as_of_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason_codes', postgresql.JSONB, nullable=False),
        sa.Column('explanation', postgresql.JSONB, nullable=False),
        sa.Column('quality_flags', postgresql.JSONB, nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            'agent_id', 'exchange', 'symbol', 'timeframe', 'feature_as_of_time', name='uq_agent_signal_key'
        )
    )
    op.create_index('ix_agent_signals_lookup', 'agent_signals', ['agent_id', 'symbol', 'timeframe', 'generated_at'])


def downgrade() -> None:
    op.drop_index('ix_agent_signals_lookup', table_name='agent_signals')
    op.drop_table('agent_signals')
    op.drop_table('agent_definitions')
    op.drop_index('ix_feature_snapshots_lookup', table_name='feature_snapshots')
    op.drop_table('feature_snapshots')
    op.drop_table('feature_sets')
    op.drop_table('feature_definitions')
