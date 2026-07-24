"""Event Bus Outbox Inbox Configuration Schema Migration

Revision ID: 002_event_bus_and_config
Revises: 001_initial_schema
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '002_event_bus_and_config'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID_TYPE = sa.Uuid().with_variant(postgresql.UUID(as_uuid=True), "postgresql")
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # 1. Event Outbox Table
    op.create_table(
        'event_outbox',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('event_id', UUID_TYPE, nullable=False, unique=True),
        sa.Column('topic', sa.String(128), nullable=False),
        sa.Column('event_type', sa.String(128), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False, default=1),
        sa.Column('aggregate_type', sa.String(64), nullable=False),
        sa.Column('aggregate_id', sa.String(128), nullable=False),
        sa.Column('payload', JSON_TYPE, nullable=False),
        sa.Column('metadata', JSON_TYPE, nullable=False),
        sa.Column('status', sa.String(32), nullable=False, default='PENDING'),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_by', sa.String(128), nullable=True)
    )
    op.create_index(
        'idx_outbox_pending_status',
        'event_outbox',
        ['status', 'next_retry_at', 'created_at']
    )

    # 2. Event Inbox Table
    op.create_table(
        'event_inbox',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('event_id', UUID_TYPE, nullable=False),
        sa.Column('consumer_name', sa.String(128), nullable=False),
        sa.Column('event_type', sa.String(128), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, default='PROCESSING'),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.UniqueConstraint('event_id', 'consumer_name', name='uq_event_consumer')
    )

    # 3. Configuration Sets Table
    op.create_table(
        'configuration_sets',
        sa.Column('id', UUID_TYPE, primary_key=True),
        sa.Column('namespace', sa.String(64), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, default='DRAFT'),
        sa.Column('values', JSON_TYPE, nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False, default='system'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('namespace', 'name', 'version', name='uq_config_namespace_name_version')
    )

    # 4. Worker Heartbeats Table
    op.create_table(
        'worker_heartbeats',
        sa.Column('worker_id', sa.String(128), primary_key=True),
        sa.Column('worker_type', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, default='RUNNING'),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('metadata', JSON_TYPE, server_default='{}')
    )


def downgrade() -> None:
    op.drop_table('worker_heartbeats')
    op.drop_table('configuration_sets')
    op.drop_table('event_inbox')
    op.drop_index('idx_outbox_pending_status', table_name='event_outbox')
    op.drop_table('event_outbox')
