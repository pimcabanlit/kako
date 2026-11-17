"""The Postgres probe and the Alembic baseline against a real, throwaway database."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.cli import main
from kako.db.engine import make_engine, probe_postgres
from tests.conftest import MakeSettings

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine(make_settings: MakeSettings, test_database_url: str) -> AsyncEngine:
    url = make_settings(database_url=test_database_url).database_url
    assert url is not None
    return make_engine(url)


async def _drop_alembic_table(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


async def test_migrate_twice_then_probe(
    engine: AsyncEngine, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _drop_alembic_table(engine)
    before = await probe_postgres(engine)
    assert before.ok
    assert "not migrated" in before.detail

    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    # The command runs its own event loop, as it does from a terminal.
    assert await asyncio.to_thread(main, ["migrate"]) == 0
    assert await asyncio.to_thread(main, ["migrate"]) == 0  # a second run changes nothing

    after = await probe_postgres(engine)
    assert after.ok
    assert after.detail.endswith("schema 0001")
    assert after.version is not None
    async with engine.connect() as conn:
        revisions = (await conn.execute(text("SELECT version_num FROM alembic_version"))).all()
    assert [r[0] for r in revisions] == ["0001"]
    await engine.dispose()


async def test_wrong_password_is_reported_without_it(make_settings: MakeSettings) -> None:
    url = make_settings(
        database_url="postgresql://kako:not-the-password@127.0.0.1:1/kako"
    ).database_url
    assert url is not None
    engine = make_engine(url)
    status = await probe_postgres(engine)
    await engine.dispose()
    assert not status.ok
    assert "not-the-password" not in status.detail
