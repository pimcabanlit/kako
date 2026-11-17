"""Integration tests run only against local services, named by test-only variables.

- KAKO_TEST_DATABASE_URL: a throwaway Postgres database (CI: a fresh service per run).
- KAKO_TEST_MEKO_URL: local Meko's MCP endpoint. A non-local URL is refused, so a test can
  never spend Meko Cloud's lifetime allowances (REVIEW.md rule 9).

Without them the tests skip, so `uv run pytest` works with nothing running. CI sets
KAKO_REQUIRE_INTEGRATION=1, which turns a missing variable into a failure instead of a skip.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.settings import LOCAL_HOSTS
from tests.conftest import MakeSettings


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if os.environ.get("KAKO_REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"{name} is not set, and KAKO_REQUIRE_INTEGRATION=1 forbids skipping")
    pytest.skip(f"{name} is not set")


@pytest.fixture
def test_database_url() -> str:
    return _required("KAKO_TEST_DATABASE_URL")


@pytest.fixture
def test_meko_url() -> str:
    url = _required("KAKO_TEST_MEKO_URL")
    if urlsplit(url).hostname not in LOCAL_HOSTS:
        pytest.fail(f"KAKO_TEST_MEKO_URL must be local Meko, not {urlsplit(url).hostname}")
    return url


async def reset_database(url: str) -> None:
    """Empty the test database: drop the `public` schema and everything in it, then recreate it.

    Only ever pointed at KAKO_TEST_DATABASE_URL, a throwaway database (CI: a fresh service).
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from kako.settings import Settings

    database_url = Settings(_env_file=None, database_url=url).database_url  # type: ignore[call-arg]
    assert database_url is not None
    engine = create_async_engine(database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def head_revision() -> str:
    """The newest Alembic revision in the repository."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from kako.cli import MIGRATIONS

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


@pytest.fixture
async def migrated(
    make_settings: MakeSettings, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncEngine]:
    """A fresh database, migrated twice (the second run must change nothing)."""
    from kako.cli import main

    await reset_database(test_database_url)
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    assert await asyncio.to_thread(main, ["migrate"]) == 0
    assert await asyncio.to_thread(main, ["migrate"]) == 0
    from kako.db.engine import make_engine

    url = make_settings(database_url=test_database_url).database_url
    assert url is not None
    engine = make_engine(url)
    yield engine
    await engine.dispose()
