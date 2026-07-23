"""add_backtest_engine_tables

Revision ID: 009_backtest_engine
Revises: 008_position_manager_and_ledger
Create Date: 2026-07-23 08:45:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = '009_backtest_engine'
down_revision: Union[str, None] = '008_position_manager_and_ledger'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. historical_datasets
    op.create_table(
        'historical_datasets',
        sa.Column('dataset_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('exchange', sa.String(50), nullable=False),
        sa.Column('symbols', JSONB, nullable=False),
        sa.Column('timeframes', JSONB, nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('candle_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('trade_count', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('quality_status', sa.String(30), nullable=False, server_default='VALIDATED'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1')
    )

    # 2. historical_dataset_versions
    op.create_table(
        'historical_dataset_versions',
        sa.Column('version_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('dataset_id', UUID(as_uuid=True), sa.ForeignKey('historical_datasets.dataset_id'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('provenance_metadata', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 3. backtest_sessions
    op.create_table(
        'backtest_sessions',
        sa.Column('session_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('mode', sa.String(30), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('dataset_id', UUID(as_uuid=True), sa.ForeignKey('historical_datasets.dataset_id'), nullable=False),
        sa.Column('dataset_checksum', sa.String(64), nullable=False),
        sa.Column('config_checksum', sa.String(64), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('warmup_start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('replay_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('events_processed', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('initial_cash', sa.Numeric(28, 8), nullable=False),
        sa.Column('final_nav', sa.Numeric(28, 8), nullable=True),
        sa.Column('random_seed', sa.Integer(), nullable=False, server_default='42'),
        sa.Column('code_version', sa.String(64), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True)
    )

    # 4. backtest_state_transitions
    op.create_table(
        'backtest_state_transitions',
        sa.Column('transition_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('from_status', sa.String(30), nullable=False),
        sa.Column('to_status', sa.String(30), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False)
    )

    # 5. backtest_config_snapshots
    op.create_table(
        'backtest_config_snapshots',
        sa.Column('snapshot_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('config_json', JSONB, nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 6. backtest_checkpoints
    op.create_table(
        'backtest_checkpoints',
        sa.Column('checkpoint_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('replay_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('events_processed', sa.BigInteger(), nullable=False),
        sa.Column('state_blob', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 7. backtest_incidents
    op.create_table(
        'backtest_incidents',
        sa.Column('incident_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('event_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 8. backtest_metrics
    op.create_table(
        'backtest_metrics',
        sa.Column('metric_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('initial_nav', sa.Numeric(28, 8), nullable=False),
        sa.Column('final_nav', sa.Numeric(28, 8), nullable=False),
        sa.Column('net_profit', sa.Numeric(28, 8), nullable=False),
        sa.Column('total_return_pct', sa.Numeric(10, 4), nullable=False),
        sa.Column('annualized_return_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('max_drawdown_pct', sa.Numeric(10, 4), nullable=False),
        sa.Column('sharpe_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('sortino_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('calmar_ratio', sa.Numeric(10, 4), nullable=True),
        sa.Column('win_rate', sa.Numeric(10, 4), nullable=False),
        sa.Column('profit_factor', sa.Numeric(10, 4), nullable=True),
        sa.Column('total_trades', sa.Integer(), nullable=False),
        sa.Column('total_fees', sa.Numeric(28, 8), nullable=False),
        sa.Column('total_slippage_cost', sa.Numeric(28, 8), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 9. backtest_equity_points
    op.create_table(
        'backtest_equity_points',
        sa.Column('point_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('nav', sa.Numeric(28, 8), nullable=False),
        sa.Column('cash_balance', sa.Numeric(28, 8), nullable=False),
        sa.Column('asset_value', sa.Numeric(28, 8), nullable=False)
    )

    # 10. backtest_drawdown_points
    op.create_table(
        'backtest_drawdown_points',
        sa.Column('point_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('drawdown_pct', sa.Numeric(10, 4), nullable=False),
        sa.Column('peak_nav', sa.Numeric(28, 8), nullable=False)
    )

    # 11. trade_episodes
    op.create_table(
        'trade_episodes',
        sa.Column('episode_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('position_id', UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('entry_quantity', sa.Numeric(28, 8), nullable=False),
        sa.Column('exit_quantity', sa.Numeric(28, 8), nullable=False),
        sa.Column('average_entry_price', sa.Numeric(28, 8), nullable=False),
        sa.Column('average_exit_price', sa.Numeric(28, 8), nullable=False),
        sa.Column('gross_pnl', sa.Numeric(28, 8), nullable=False),
        sa.Column('fees', sa.Numeric(28, 8), nullable=False),
        sa.Column('slippage_cost', sa.Numeric(28, 8), nullable=False),
        sa.Column('net_pnl', sa.Numeric(28, 8), nullable=False),
        sa.Column('exit_reason', sa.String(50), nullable=False)
    )

    # 12. trade_attributions
    op.create_table(
        'trade_attributions',
        sa.Column('attribution_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('episode_id', UUID(as_uuid=True), sa.ForeignKey('trade_episodes.episode_id'), nullable=False),
        sa.Column('agent_name', sa.String(50), nullable=False),
        sa.Column('weight', sa.Numeric(10, 4), nullable=False),
        sa.Column('attributed_pnl', sa.Numeric(28, 8), nullable=False)
    )

    # 13. walk_forward_folds
    op.create_table(
        'walk_forward_folds',
        sa.Column('fold_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('fold_number', sa.Integer(), nullable=False),
        sa.Column('train_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('train_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('validation_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('validation_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('test_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('test_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('test_nav', sa.Numeric(28, 8), nullable=True)
    )

    # 14. backtest_benchmarks
    op.create_table(
        'backtest_benchmarks',
        sa.Column('benchmark_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('final_nav', sa.Numeric(28, 8), nullable=False),
        sa.Column('total_return_pct', sa.Numeric(10, 4), nullable=False),
        sa.Column('max_drawdown_pct', sa.Numeric(10, 4), nullable=False)
    )

    # 15. backtest_reports
    op.create_table(
        'backtest_reports',
        sa.Column('report_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('reproducibility_fingerprint', sa.String(64), nullable=False),
        sa.Column('report_json', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 16. backtest_reproducibility_checks
    op.create_table(
        'backtest_reproducibility_checks',
        sa.Column('check_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('backtest_sessions.session_id'), nullable=False),
        sa.Column('reproduced_session_id', UUID(as_uuid=True), nullable=False),
        sa.Column('is_identical', sa.Boolean(), nullable=False),
        sa.Column('diff_summary', JSONB, nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False)
    )


def downgrade() -> None:
    op.drop_table('backtest_reproducibility_checks')
    op.drop_table('backtest_reports')
    op.drop_table('backtest_benchmarks')
    op.drop_table('walk_forward_folds')
    op.drop_table('trade_attributions')
    op.drop_table('trade_episodes')
    op.drop_table('backtest_drawdown_points')
    op.drop_table('backtest_equity_points')
    op.drop_table('backtest_metrics')
    op.drop_table('backtest_incidents')
    op.drop_table('backtest_checkpoints')
    op.drop_table('backtest_config_snapshots')
    op.drop_table('backtest_state_transitions')
    op.drop_table('backtest_sessions')
    op.drop_table('historical_dataset_versions')
    op.drop_table('historical_datasets')
