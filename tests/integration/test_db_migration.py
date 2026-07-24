import os

import pytest

try:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    ALEMBIC_AVAILABLE = True
except ImportError:
    ALEMBIC_AVAILABLE = False


@pytest.mark.skipif(not ALEMBIC_AVAILABLE, reason="Alembic / SQLAlchemy not installed in local runner environment")
def test_alembic_migration_lifecycle():
    """Tests Alembic 001 and 002 upgrade, downgrade, and re-upgrade on SQLite/Postgres engine."""
    db_path = "/tmp/test_milestone_2_migration.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)

    # Setup Alembic Config pointing to project migrations
    alembic_cfg = Config("infra/migrations/alembic.ini")
    assert alembic_cfg.get_main_option("sqlalchemy.url") == ""
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", "infra/migrations")

    # Step 1: Upgrade to 001
    command.upgrade(alembic_cfg, "001_initial_schema")
    inspector = inspect(engine)
    tables_001 = inspector.get_table_names()
    assert "orders" in tables_001
    assert "incidents" in tables_001
    assert "audit_events" in tables_001

    # Step 2: Upgrade to 002
    command.upgrade(alembic_cfg, "002_event_bus_and_config")
    inspector = inspect(engine)
    tables_002 = inspector.get_table_names()
    assert "event_outbox" in tables_002
    assert "event_inbox" in tables_002
    assert "configuration_sets" in tables_002
    assert "worker_heartbeats" in tables_002

    # Step 3: Downgrade 002
    command.downgrade(alembic_cfg, "001_initial_schema")
    inspector = inspect(engine)
    tables_downgraded = inspector.get_table_names()
    assert "event_outbox" not in tables_downgraded
    assert "event_inbox" not in tables_downgraded
    assert "orders" in tables_downgraded
    assert "audit_events" in tables_downgraded

    # Step 4: Re-upgrade to 002
    command.upgrade(alembic_cfg, "002_event_bus_and_config")
    inspector = inspect(engine)
    tables_reup = inspector.get_table_names()
    assert "event_outbox" in tables_reup
    assert "event_inbox" in tables_reup

    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)
