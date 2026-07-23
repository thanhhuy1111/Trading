"""Milestone 12: Security Review, System Hardening & Production Readiness Tables

Revision ID: 012_security_hardening
Revises: 011_observability
Create Date: 2026-07-23

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '012_security_hardening'
down_revision = '011_observability'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. security_findings
    op.create_table(
        'security_findings',
        sa.Column('finding_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scanner', sa.String(50), nullable=False),
        sa.Column('rule_id', sa.String(100), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('component', sa.String(100), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='OPEN'),
        sa.Column('first_detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 2. security_scan_runs
    op.create_table(
        'security_scan_runs',
        sa.Column('scan_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scan_type', sa.String(50), nullable=False),
        sa.Column('target', sa.String(100), nullable=False),
        sa.Column('total_findings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('critical_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('high_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 3. security_control_matrix
    op.create_table(
        'security_control_matrix',
        sa.Column('control_id', sa.String(50), primary_key=True),
        sa.Column('standard', sa.String(50), nullable=False),
        sa.Column('requirement', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PASS'),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('owner', sa.String(100), nullable=False)
    )

    # 4. security_risk_register
    op.create_table(
        'security_risk_register',
        sa.Column('risk_id', sa.String(50), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('asset', sa.String(100), nullable=False),
        sa.Column('threat', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='MITIGATED'),
        sa.Column('owner', sa.String(100), nullable=False)
    )

    # 5. accepted_security_risks
    op.create_table(
        'accepted_security_risks',
        sa.Column('risk_acceptance_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('risk_id', sa.String(50), nullable=False),
        sa.Column('owner', sa.String(100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('compensating_control', sa.Text(), nullable=False),
        sa.Column('expiration_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 6. security_incidents
    op.create_table(
        'security_incidents',
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='OPEN'),
        sa.Column('reported_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 7. security_incident_transitions
    op.create_table(
        'security_incident_transitions',
        sa.Column('transition_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'incident_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('security_incidents.incident_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('from_status', sa.String(30), nullable=False),
        sa.Column('to_status', sa.String(30), nullable=False),
        sa.Column('transitioned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 8. security_release_candidates
    op.create_table(
        'security_release_candidates',
        sa.Column('release_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('git_commit', sa.String(40), nullable=False),
        sa.Column('migration_head', sa.String(50), nullable=False),
        sa.Column('sbom_checksum', sa.String(64), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='APPROVED'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 9. artifact_inventory
    op.create_table(
        'artifact_inventory',
        sa.Column('artifact_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 10. sbom_records
    op.create_table(
        'sbom_records',
        sa.Column('sbom_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('format', sa.String(30), nullable=False, server_default='CycloneDX'),
        sa.Column('total_packages', sa.Integer(), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 11. backup_records
    op.create_table(
        'backup_records',
        sa.Column('backup_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('backup_type', sa.String(50), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='SUCCESS'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 12. restore_test_records
    op.create_table(
        'restore_test_records',
        sa.Column('restore_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'backup_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('backup_records.backup_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('is_reconciliation_passed', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('duration_ms', sa.Float(), nullable=False),
        sa.Column('tested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 13. security_exception_approvals
    op.create_table(
        'security_exception_approvals',
        sa.Column('exception_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('approver', sa.String(100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )


def downgrade() -> None:
    op.drop_table('security_exception_approvals')
    op.drop_table('restore_test_records')
    op.drop_table('backup_records')
    op.drop_table('sbom_records')
    op.drop_table('artifact_inventory')
    op.drop_table('security_release_candidates')
    op.drop_table('security_incident_transitions')
    op.drop_table('security_incidents')
    op.drop_table('accepted_security_risks')
    op.drop_table('security_risk_register')
    op.drop_table('security_control_matrix')
    op.drop_table('security_scan_runs')
    op.drop_table('security_findings')
