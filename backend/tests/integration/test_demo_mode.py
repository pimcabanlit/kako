"""`kako demo run` (Phase 3, task 9): the demo household and its recorded sessions on local Postgres
and local Meko, with no Azure settings at all. Every model reply comes from `data/recorded/`,
replayed strictly, so this also proves the recordings replay on a database other than the one they
were recorded on (the entities' ids differ)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.evals.questions import TEST_SET
from kako.settings import get_settings

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
RESULTS = TEST_SET.parent / "results"


@pytest.fixture
def demo_env(test_database_url: str, test_meko_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the database and local Meko: no Foundry endpoint, deployment or Azure sign-in."""
    for name in list(os.environ):
        if name.startswith("AZURE_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    monkeypatch.setenv("MEKO_MCP_URL", test_meko_url)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.foundry_endpoint is None
    assert settings.model_strong is None
    assert settings.model_fast is None


async def test_demo_run_replays_session_2_and_the_test_set(
    migrated: AsyncEngine, demo_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await asyncio.to_thread(_main, ["demo", "run", "--test-set"]) == 0
    out = capsys.readouterr().out
    assert "Villanueva household: loaded with its whole story; 15 documents" in out
    assert "== Session 2, turn s2:t1 ==" in out
    assert "A: all extra on the card" in out
    assert "B: Jun\u2019s split" in out
    assert "US$0.0000." in out  # replayed, so nothing spent
    # The test set replays on this database to the score its saved run reports.
    saved = json.loads((RESULTS / "specialists.json").read_text(encoding="utf-8"))
    n = saved["questions"]
    checks = f"({saved['checks_passed']}/{saved['checks_total']} checks), {n} answered"
    line = next(x for x in out.splitlines() if x.startswith("Agent test set (specialists): "))
    assert f"over {n} questions {checks}" in line
    assert "Demo mode replayed 1 session(s) from recordings" in out
    async with migrated.connect() as conn:
        replayed = list(
            await conn.execute(text("SELECT recorded_replay, count(*) FROM llm_call GROUP BY 1"))
        )
        plans = (await conn.execute(text("SELECT count(*) FROM plan"))).scalar_one()
    # Every call is logged, and every one is a replay: no model was called.
    assert [r for r, _ in replayed] == [True]
    assert plans >= 1

    # A second run keeps the household and the documents, and replays session 2 again.
    assert await asyncio.to_thread(_main, ["demo", "run"]) == 0
    out = capsys.readouterr().out
    assert (
        "Villanueva household: already loaded; 15 documents searchable in local Meko (0 new)" in out
    )
    assert "== Session 2, turn s2:t1 ==" in out


async def test_demo_run_refuses_part_of_the_story(
    migrated: AsyncEngine,
    demo_env: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo(), through=datetime(2026, 9, 15, 9, tzinfo=MANILA))
        await conn.commit()
    assert await asyncio.to_thread(_main, ["demo", "run"]) == 1
    err = capsys.readouterr().err
    assert "demo mode needs the whole story, so use an empty database" in err


async def test_demo_run_refuses_meko_cloud(
    demo_env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MEKO_MCP_URL", "https://mcp.mekodata.ai/mcp")
    get_settings.cache_clear()
    assert await asyncio.to_thread(_main, ["demo", "run"]) == 1
    assert "demo mode runs on local Meko" in capsys.readouterr().err


def _main(args: list[str]) -> int:
    from kako.cli import main

    return main(args)
