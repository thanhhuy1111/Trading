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

UUID_TYPE = sa.Uuid().with_variant(postgresql.UUID(as_uuid=True), "postgresql")
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # NOTE (Round 4 durability fix): this initial migration originally also declared
    # 'exchanges', 'symbols', 'trade_intents', 'risk_decisions', 'fills', 'positions', and
    # 'portfolio_snapshots' with an early draft schema. Each was later redeclared with the
    # real/complete schema by a milestone migration (003, 005, 006, 007, 008 respectively),
    # which made `alembic upgrade head` fail on any fresh database with DuplicateTableError
    # (never previously caught because this chain had never been run against a real Postgres
    # before). Removed here since 001 never shipped against a live database; the milestone
    # migrations are now the sole owners of those seven tables.

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

    # 9. Incidents
    op.create_table(
        'incidents',
        sa.Column('incident_id', UUID_TYPE, primary_key=True),
        sa.Column('severity', sa.String(32), nullable=False),
        sa.Column('service_name', sa.String(64), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details', JSON_TYPE, server_default='{}'),
        sa.Column('is_acknowledged', sa.Boolean(), default=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

    # 10. Audit Log (Append-Only)
    op.create_table(
        'audit_events',
        sa.Column('event_id', UUID_TYPE, primary_key=True),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('service_name', sa.String(64), nullable=False),
        sa.Column('actor', sa.String(64), default='system'),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('payload', JSON_TYPE, server_default='{}')
    )


def downgrade() -> None:
    op.drop_table('audit_events')
    op.drop_table('incidents')
    op.drop_table('orders')
