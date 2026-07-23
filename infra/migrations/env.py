import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from packages.common.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = settings.DATABASE_URL.replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_version_column_width(connection: Connection) -> None:
    """Alembic's default alembic_version.version_num is VARCHAR(32); some revision ids in
    this project (e.g. '007_execution_engine_and_simulator', 34 chars) exceed that. Widen it
    idempotently before running migrations. This touches only Alembic's own bookkeeping table,
    never the content of a versioned migration file."""
    from sqlalchemy import text
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(255) NOT NULL)"
    ))
    connection.execute(text(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"
    ))
    # Commit this preparatory DDL now so Alembic's own context.begin_transaction() starts a
    # fresh transaction rather than nesting inside (and silently depending on) this one.
    connection.commit()


def do_run_migrations(connection: Connection) -> None:
    _ensure_version_column_width(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
