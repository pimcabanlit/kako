"""The async SQLAlchemy engine and the Postgres health probe."""

from __future__ import annotations

import logging
import time

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from kako.health import ServiceStatus, safe_error

logger = logging.getLogger(__name__)


def make_engine(database_url: SecretStr) -> AsyncEngine:
    """An engine for the app. `pool_pre_ping` drops connections a managed Postgres closed."""
    return create_async_engine(database_url.get_secret_value(), pool_pre_ping=True)


async def probe_postgres(engine: AsyncEngine | None) -> ServiceStatus:
    """Connect, read the server version and the Alembic revision. Never raises."""
    if engine is None:
        return ServiceStatus(ok=False, detail="not configured: set KAKO_DATABASE_URL")
    started = time.perf_counter()
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SHOW server_version"))).scalar_one()
            try:
                revision = (
                    await conn.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
            except ProgrammingError:
                # No alembic_version table yet: reachable, but `kako migrate` has not run.
                await conn.rollback()
                revision = None
    except Exception as exc:  # noqa: BLE001 - a health probe reports every failure, never raises
        logger.warning("Postgres health probe failed: %s", safe_error(exc))
        return ServiceStatus(ok=False, detail=safe_error(exc), latency_ms=_ms(started))
    schema = f"schema {revision}" if revision else "not migrated (run `kako migrate`)"
    return ServiceStatus(
        ok=True,
        detail=f"PostgreSQL {str(version).split()[0]}, {schema}",
        latency_ms=_ms(started),
        version=str(version).split()[0],
    )


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
