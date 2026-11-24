"""`kako ask`: one planning turn on the demo household, recorded, then replayed by the command
with no network. The recording comes from the scripted model, never Foundry."""

from __future__ import annotations

import asyncio
import json
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
from tests.support.models import ScriptedBackend, calls
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
    async with migrated.connect() as conn:
        checks = list(
            await conn.execute(
                text(
                    "SELECT n.subject, n.result, n.calc_run_id = r.id FROM number_check n "
                    "JOIN calc_run r ON r.id = n.calc_run_id "
                    "WHERE n.session_id = :s ORDER BY n.created_at"
                ),
                {"s": asked.session_id},
            )
        )
    # Every text checked against the turn's stored run: the two specialists' summaries, then the
    # reply, each option's label and summary, and the resolution's reason. All pass.
    assert [tuple(r) for r in checks] == [
        ("recommendation", "pass", True),
        ("recommendation", "pass", True),
        ("reply", "pass", True),
        *[("recommendation", "pass", True)] * 4,
        ("reconciliation", "pass", True),
    ]

    # The command answers the same turn from the recording, with no model and no Meko.
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    monkeypatch.setenv("KAKO_MODEL_MODE", "replay")
    monkeypatch.setenv("KAKO_RECORDED_RESPONSES", str(path))
    args = ["ask", SESSION_2, "--on", "2026-09-15", "--seed", SEED, "--no-meko"]
    get_settings.cache_clear()  # read the settings again, with the replay
    assert await asyncio.to_thread(_main, [*args, "--by", "Nobody"]) == 1
    assert "No one called Nobody in the household." in capsys.readouterr().err
    assert await asyncio.to_thread(_main, [*args, "--title", "Session 2", "--by", "Mara"]) == 0
    out = capsys.readouterr().out
    assert "B: split: Card paid off in 17 months" in out
    assert "US$0.0000." in out  # a replay costs nothing


async def test_a_planted_wrong_number_is_regenerated_and_logged(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    """Phase 3, task 5, done when: a planted wrong number is caught, regenerated, and logged in
    `number_check`. The reply first says A is "8 months faster" (17 minus 9, worked out, not a
    figure); the check sends it back naming that number, and the second reply passes."""
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 9, 15, 9, tzinfo=MANILA)
        )
        await conn.commit()
    turn = script()
    good = json.loads(turn[f"{SEED}/orchestrator/2"].tool_calls[0].arguments)
    planted = {**good, "reply": "A clears the card 8 months faster than B."}
    turn[f"{SEED}/orchestrator/2"] = calls(("submit_answer", planted))
    turn[f"{SEED}/orchestrator/3"] = calls(("submit_answer", good))
    backend = ScriptedBackend(turn)
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    asked = await ask(
        migrated,
        None,
        settings,
        backend,
        household_id=household_id,
        message=SESSION_2,
        on=SEP_15,
        known_at=None,
        title="Session 2",
        seed=SEED,
    )
    assert asked.answer.reply == good["reply"]
    told = next(r for k, _, r in backend.requests if k == f"{SEED}/orchestrator/3")
    assert "'8 months' in the reply" in (told.messages[-1].content or "")
    async with migrated.connect() as conn:
        rows = list(
            await conn.execute(
                text(
                    "SELECT checked_text, numbers, result FROM number_check "
                    "WHERE session_id = :s AND subject = 'reply' ORDER BY created_at"
                ),
                {"s": asked.session_id},
            )
        )
    assert [(r.checked_text, r.result) for r in rows] == [
        (planted["reply"], "regenerated"),
        (good["reply"], "pass"),
    ]
    assert rows[0].numbers == [{"text": "8 months", "kind": "months", "match": None}]


def _main(args: list[str]) -> int:
    from kako.cli import main

    return main(args)
