"""`kako ask`: one planning turn on the demo household, recorded, then replayed by the command
with no network. The recording comes from the scripted model, never Foundry."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import ask, render_answer
from kako.agents.recorded import RecordingBackend
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.settings import get_settings
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend
from tests.support.villanueva import SEP_15
from tests.test_agents_turn import SEED, SESSION_2
from tests.test_agents_turn import _session_2_script as script

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))


async def test_ask_records_and_the_command_replays(
    migrated: AsyncEngine,
    test_database_url: str,
    make_settings: MakeSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 9, 15, 9, tzinfo=MANILA)
        )
        await conn.commit()
    path = tmp_path / "session-2.json"
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    asked = await ask(
        migrated,
        None,
        settings,
        RecordingBackend(ScriptedBackend(script()), path),
        household_id=household_id,
        message=SESSION_2,
        on=SEP_15,
        known_at=None,
        title="Session 2",
        seed=SEED,
    )
    printed = render_answer(asked)
    assert "A: all extra on the card: Card paid off in 9 months" in printed
    assert "  debt:credit-card: ₱4,000.00 a month (said:4000)" in printed
    assert "  account:emergency-fund: ₱5,050.00 a month (rest)" in printed
    assert "  cites figure:savings1-W1:savings.months_to_target = 12 months" in printed
    assert f"Turn {SEED}, session {asked.session_id}: 6 model calls" in printed
    async with migrated.connect() as conn:
        steps = (
            await conn.execute(
                text("SELECT count(*) FROM agent_step WHERE session_id = :s"),
                {"s": asked.session_id},
            )
        ).scalar_one()
    assert steps == 8

    # The command answers the same turn from the recording, with no model and no Meko.
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    monkeypatch.setenv("KAKO_MODEL_MODE", "replay")
    monkeypatch.setenv("KAKO_RECORDED_RESPONSES", str(path))
    args = ["ask", SESSION_2, "--on", "2026-09-15", "--seed", SEED, "--no-meko"]
    get_settings.cache_clear()  # read the settings again, with the replay
    assert await asyncio.to_thread(_main, [*args, "--title", "Session 2"]) == 0
    out = capsys.readouterr().out
    assert "B: split: Card paid off in 17 months" in out
    assert "US$0.0000." in out  # a replay costs nothing


def _main(args: list[str]) -> int:
    from kako.cli import main

    return main(args)
