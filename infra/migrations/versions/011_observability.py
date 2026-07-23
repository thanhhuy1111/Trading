"""Milestone 11: Observability, Alerting & Incident Management Tables

Revision ID: 011_observability
Revises: 010_paper_trading
Create Date: 2026-07-23

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '011_observability'
down_revision = '010_paper_trading'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. operational_incidents
    op.create_table(
        'operational_incidents',
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('component', sa.String(100), nullable=False),
        sa.Column('incident_type', sa.String(100), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('first_detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('occurrence_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('correlation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('symbol', sa.String(50), nullable=True),
        sa.Column('runbook_reference', sa.String(200), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.String(100), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1')
    )

    # 2. incident_state_transitions
    op.create_table(
        'incident_state_transitions',
        sa.Column('transition_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'incident_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('operational_incidents.incident_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('from_status', sa.String(30), nullable=False),
        sa.Column('to_status', sa.String(30), nullable=False),
        sa.Column('actor', sa.String(100), nullable=False, server_default='SYSTEM'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('transitioned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 3. incident_notes
    op.create_table(
        'incident_notes',
        sa.Column('note_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'incident_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('operational_incidents.incident_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('author', sa.String(100), nullable=False),
        sa.Column('note_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 4. component_health_snapshots
    op.create_table(
        'component_health_snapshots',
        sa.Column('health_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('component_name', sa.String(100), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('last_successful_op', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('latency_ms', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 5. slo_definitions
    op.create_table(
        'slo_definitions',
        sa.Column('slo_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('target_percentage', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('window_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 6. slo_measurements
    op.create_table(
        'slo_measurements',
        sa.Column('measurement_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'slo_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('slo_definitions.slo_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('current_value_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('error_budget_remaining_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 7. alert_rule_metadata
    op.create_table(
        'alert_rule_metadata',
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('component', sa.String(100), nullable=False),
        sa.Column('for_duration_seconds', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('runbook_url', sa.String(250), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true')
    )

    # 8. alert_occurrences
    op.create_table(
        'alert_occurrences',
        sa.Column('occurrence_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'rule_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('alert_rule_metadata.rule_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 9. pipeline_lineage_records
    op.create_table(
        'pipeline_lineage_records',
        sa.Column('lineage_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('parent_entity_type', sa.String(100), nullable=True),
        sa.Column('parent_entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('correlation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('causation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('symbol', sa.String(50), nullable=True),
        sa.Column('service', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 10. observability_config_snapshots
    op.create_table(
        'observability_config_snapshots',
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('config_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('config_checksum', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 11. retention_policy_runs
    op.create_table(
        'retention_policy_runs',
        sa.Column('run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('target_table', sa.String(100), nullable=False),
        sa.Column('deleted_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_dry_run', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )


def downgrade() -> None:
    op.drop_table('retention_policy_runs')
    op.drop_table('observability_config_snapshots')
    op.drop_table('pipeline_lineage_records')
    op.drop_table('alert_occurrences')
    op.drop_table('alert_rule_metadata')
    op.drop_table('slo_measurements')
    op.drop_table('slo_definitions')
    op.drop_table('component_health_snapshots')
    op.drop_table('incident_notes')
    op.drop_table('incident_state_transitions')
    op.drop_table('operational_incidents')
