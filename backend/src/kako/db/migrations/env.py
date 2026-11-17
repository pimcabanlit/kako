"""Alembic's environment: migrations run online, over asyncpg, against KAKO_DATABASE_URL."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import kako.db.models  # noqa: F401 - registers every table on Base.metadata
from kako.db.base import Base
from kako.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    url = get_settings().database_url
    if url is None:
        raise SystemExit("KAKO_DATABASE_URL is not set.")
    engine = create_async_engine(url.get_secret_value(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) migrations are not used; run them against a database.")
asyncio.run(_run_online())
