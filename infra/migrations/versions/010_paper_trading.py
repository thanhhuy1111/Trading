"""Milestone 10: Real-Time Paper Trading Tables

Revision ID: 010_paper_trading
Revises: 009_backtest_engine
Create Date: 2026-07-23

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '010_paper_trading'
down_revision = '009_backtest_engine'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. paper_sessions
    op.create_table(
        'paper_sessions',
        sa.Column('session_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('account_id', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False, server_default='binance'),
        sa.Column('symbols', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('timeframes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('initial_cash', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('base_currency', sa.String(20), nullable=False, server_default='USDT'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('warmup_start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_market_event_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_processed_event_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('config_snapshot_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('config_fingerprint', sa.String(64), nullable=False),
        sa.Column('code_version', sa.String(50), nullable=False, server_default='1.0.0'),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 2. paper_session_transitions
    op.create_table(
        'paper_session_transitions',
        sa.Column('transition_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('from_status', sa.String(50), nullable=False),
        sa.Column('to_status', sa.String(50), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('transitioned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 3. paper_config_snapshots
    op.create_table(
        'paper_config_snapshots',
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('config_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('config_fingerprint', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 4. paper_accounts
    op.create_table(
        'paper_accounts',
        sa.Column('account_id', sa.String(100), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('initial_cash', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('current_cash', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('base_currency', sa.String(20), nullable=False, server_default='USDT'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 5. paper_event_journal
    op.create_table(
        'paper_event_journal',
        sa.Column('journal_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source', sa.String(100), nullable=False),
        sa.Column('exchange_event_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sequence_number', sa.BigInteger(), nullable=True),
        sa.Column('payload_checksum', sa.String(64), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1')
    )

    # 6. paper_market_checkpoints
    op.create_table(
        'paper_market_checkpoints',
        sa.Column('checkpoint_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('last_event_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stream_sequence', sa.BigInteger(), nullable=False),
        sa.Column('checkpoint_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 7. paper_runtime_health
    op.create_table(
        'paper_runtime_health',
        sa.Column('health_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('connection_state', sa.String(50), nullable=False),
        sa.Column('clock_skew_ms', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('stream_healthy', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_ping_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 8. paper_connection_incidents
    op.create_table(
        'paper_connection_incidents',
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('incident_type', sa.String(100), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 9. paper_gap_recoveries
    op.create_table(
        'paper_gap_recoveries',
        sa.Column('recovery_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('gap_start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('gap_end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recovered_candle_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(50), nullable=False, server_default='COMPLETED'),
        sa.Column('recovered_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 10. paper_clock_skew_incidents
    op.create_table(
        'paper_clock_skew_incidents',
        sa.Column('incident_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('skew_ms', sa.Float(), nullable=False),
        sa.Column('threshold_ms', sa.Float(), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 11. paper_daily_metrics
    op.create_table(
        'paper_daily_metrics',
        sa.Column('metric_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('opening_nav', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('closing_nav', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('daily_pnl', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('trade_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 12. paper_reports
    op.create_table(
        'paper_reports',
        sa.Column('report_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('nav', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('total_return_pct', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('max_drawdown_pct', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('win_rate', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('trade_count', sa.Integer(), nullable=False),
        sa.Column('config_fingerprint', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    # 13. paper_backtest_comparisons
    op.create_table(
        'paper_backtest_comparisons',
        sa.Column('comparison_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'paper_session_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('paper_sessions.session_id', ondelete='CASCADE'),
            nullable=False
        ),
        sa.Column('backtest_session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('paper_nav', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('backtest_nav', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('nav_diff_pct', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('slippage_diff_bps', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('trade_count_diff', sa.Integer(), nullable=False),
        sa.Column('compared_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )


def downgrade() -> None:
    op.drop_table('paper_backtest_comparisons')
    op.drop_table('paper_reports')
    op.drop_table('paper_daily_metrics')
    op.drop_table('paper_clock_skew_incidents')
    op.drop_table('paper_gap_recoveries')
    op.drop_table('paper_connection_incidents')
    op.drop_table('paper_runtime_health')
    op.drop_table('paper_market_checkpoints')
    op.drop_table('paper_event_journal')
    op.drop_table('paper_accounts')
    op.drop_table('paper_config_snapshots')
    op.drop_table('paper_session_transitions')
    op.drop_table('paper_sessions')
