"""Governance Layer and Trade Intents Schema Migration

Revision ID: 005_governance_and_intents
Revises: 004_features_and_agents
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '005_governance_and_intents'
down_revision: Union[str, None] = '004_features_and_agents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Critic Decisions Table
    op.create_table(
        'critic_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('decision_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('signal_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', sa.String(64), nullable=False),
        sa.Column('approved_for_aggregation', sa.Boolean, nullable=False),
        sa.Column('original_confidence', sa.Numeric(6, 4), nullable=False),
        sa.Column('adjusted_confidence', sa.Numeric(6, 4), nullable=False),
        sa.Column('confidence_penalty', sa.Numeric(6, 4), nullable=False),
        sa.Column('estimated_cost_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('risk_flags', postgresql.JSONB, nullable=False),
        sa.Column('warning_codes', postgresql.JSONB, nullable=False),
        sa.Column('rejection_codes', postgresql.JSONB, nullable=False),
        sa.Column('review_components', postgresql.JSONB, nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('critic_version', sa.String(16), nullable=False),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('signal_id', 'critic_version', 'policy_version', name='uq_critic_decision_signal_ver')
    )

    # 2. Consensus Results Table
    op.create_table(
        'consensus_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('consensus_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('direction', sa.String(32), nullable=False),
        sa.Column('agreement_score', sa.Numeric(6, 4), nullable=False),
        sa.Column('disagreement_score', sa.Numeric(6, 4), nullable=False),
        sa.Column('participating_signals', postgresql.JSONB, nullable=False),
        sa.Column('accepted_signals', postgresql.JSONB, nullable=False),
        sa.Column('rejected_signals', postgresql.JSONB, nullable=False),
        sa.Column('weighted_confidence', sa.Numeric(6, 4), nullable=False),
        sa.Column('weighted_expected_return_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('reason_codes', postgresql.JSONB, nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consensus_version', sa.String(16), nullable=False)
    )

    # 3. Allocation Decisions Table
    op.create_table(
        'allocation_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('allocation_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('result', sa.String(32), nullable=False),
        sa.Column('consensus_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_signal_ids', postgresql.JSONB, nullable=False),
        sa.Column('critic_decision_ids', postgresql.JSONB, nullable=False),
        sa.Column('created_trade_intent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reason_codes', postgresql.JSONB, nullable=False),
        sa.Column('decision_fingerprint', sa.String(64), nullable=False, unique=True),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('allocator_version', sa.String(16), nullable=False),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 4. Trade Intents Table (NO quantity, NO notional, NO leverage)
    op.create_table(
        'trade_intents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('exchange', sa.String(32), nullable=False),
        sa.Column('side', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='PENDING_RISK_REVIEW'),
        sa.Column('strategy_ids', postgresql.JSONB, nullable=False),
        sa.Column('source_signal_ids', postgresql.JSONB, nullable=False),
        sa.Column('critic_decision_ids', postgresql.JSONB, nullable=False),
        sa.Column('consensus_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('market_regime', sa.String(32), nullable=False),
        sa.Column('expected_return_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('weighted_confidence', sa.Numeric(6, 4), nullable=False),
        sa.Column('estimated_fee_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('estimated_spread_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('estimated_slippage_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('uncertainty_buffer_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('net_edge_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('reference_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('invalidation_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('suggested_stop_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('suggested_take_profit_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('horizon_minutes', sa.Integer, nullable=False),
        sa.Column('maximum_entry_slippage_bps', sa.Numeric(12, 4), nullable=False),
        sa.Column('feature_as_of_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason_codes', postgresql.JSONB, nullable=False),
        sa.Column('policy_version', sa.String(16), nullable=False),
        sa.Column('allocator_version', sa.String(16), nullable=False),
        sa.Column('schema_version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_trade_intents_lookup', 'trade_intents', ['symbol', 'status', 'generated_at'])


def downgrade() -> None:
    op.drop_index('ix_trade_intents_lookup', table_name='trade_intents')
    op.drop_table('trade_intents')
    op.drop_table('allocation_decisions')
    op.drop_table('consensus_results')
    op.drop_table('critic_decisions')
