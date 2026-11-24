"""`kako demo run` (Phase 3, task 9): the demo household and its recorded sessions on local Postgres
and local Meko, with no Azure settings at all. Every model reply comes from `data/recorded/`,
replayed strictly, so this also proves the recordings replay on a database other than the one they
were recorded on (the entities' ids differ)."""

from __future__ import annotations

import asyncio
import json
import os
import warnings
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.recorded import RecordingBackend, RecordingError
from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.demo.mode import DemoModeError, replay_session, written
from kako.demo.sessions import check_writes, read_sessions
from kako.evals.questions import TEST_SET
from kako.meko.mcp import open_meko
from kako.settings import get_settings
from tests.conftest import MakeSettings
from tests.integration import test_replan as replan_turns
from tests.integration.test_meko_adapter import throwaway_datapack
from tests.support.models import ScriptedBackend, calls

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
RESULTS = TEST_SET.parent / "results"
PEOPLE = frozenset(p.key for p in read_demo().people)


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
    migrated: AsyncEngine,
    demo_env: None,
    test_meko_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with throwaway_datapack(test_meko_url) as datapack_id:
        # A datapack of its own: Kako's memories of the story don't pile up in the default one.
        monkeypatch.setenv("KAKO_MEKO_DATAPACK_ID", datapack_id)
        get_settings.cache_clear()
        await _demo_run_twice(migrated, capsys)
    get_settings.cache_clear()


async def _demo_run_twice(migrated: AsyncEngine, capsys: pytest.CaptureFixture[str]) -> None:
    assert await asyncio.to_thread(_main, ["demo", "run", "--test-set"]) == 0
    out = capsys.readouterr().out
    assert "Villanueva household: loaded with its whole story; 15 documents" in out
    assert "== Session 2, turn s2:t1 ==" in out
    assert "A: all extra on the card" in out
    assert "B: Jun's split" in out
    # Session 4: the new job proposed, approved by Mara in the story, then the three-part replan.
    assert "== Session 4, turn s4:t1 ==" in out
    assert "replace_fact: Mara's salary: income.monthly_net = ₱68,000.00 from Dec 1, 2026" in out
    assert "== Session 4, turn s4:t2 ==\nThe new plan:" in out
    assert "What changed since the decision of Sep 15, 2026 in Session 2 (B: split):" in out
    assert "- Take-home pay a month, all incomes: ₱100,000.00 → ₱116,000.00" in out
    assert "\nWhy:\n" in out
    assert "- To revisit: “How hard should we pay down the credit card?”" in out
    assert "US$0.0000." in out  # replayed, so nothing spent
    # The test set replays on this database to the score its saved run reports.
    saved = json.loads((RESULTS / "specialists.json").read_text(encoding="utf-8"))
    n = saved["questions"]
    checks = f"({saved['checks_passed']}/{saved['checks_total']} checks), {n} answered"
    line = next(x for x in out.splitlines() if x.startswith("Agent test set (specialists): "))
    assert f"over {n} questions {checks}" in line
    assert "Demo mode replayed 2 session(s) from recordings" in out
    for line in out.splitlines():  # shown in the run's warnings, so a machine's drift is seen
        if "requests differed from the recording" in line:
            warnings.warn(line, stacklevel=1)
    async with migrated.connect() as conn:
        replayed = list(
            await conn.execute(text("SELECT recorded_replay, count(*) FROM llm_call GROUP BY 1"))
        )
        plans = (await conn.execute(text("SELECT count(*) FROM plan"))).scalar_one()
    # Every call is logged, and every one is a replay: no model was called.
    assert [r for r, _ in replayed] == [True]
    assert plans >= 1

    async with migrated.connect() as conn:
        events = (await conn.execute(text("SELECT count(*) FROM life_event"))).scalar_one()
        facts = (
            await conn.execute(text("SELECT count(*) FROM fact WHERE status <> 'retracted'"))
        ).scalar_one()
    assert events == 1  # written by session 4's approval, not by loading

    # After the sessions, Meko upkeep keeps every fact; a memory search for Mara's salary finds
    # the new one and the old one in the past tense (Phase 4, task 5), and V-13 passes.
    assert f"Meko upkeep: {facts} memories added, 0 rewritten, 0 deleted." in out
    async with open_meko(get_settings(), DbCallLog(migrated), max_calls=2) as meko:
        conversation_id = await meko.create_conversation(agent_id="kako:test", title="check")
        found = [
            m.text
            for m in await meko.find_memories(
                conversation_id, "Mara's salary", agent_id="kako:test", limit=10
            )
        ]
    assert (
        "In the Villanueva household, from Dec 1, 2026, Mara's salary (take-home pay a month) "
        "is ₱68,000.00." in found
    )
    assert (
        "In the Villanueva household, from Mar 1, 2026 until Nov 30, 2026, Mara's salary "
        "(take-home pay a month) was ₱52,000.00." in found
    )
    assert await asyncio.to_thread(_main, ["meko", "check"]) == 0
    assert "V-13 passes" in capsys.readouterr().out

    # A second run keeps the household and the documents, and replays session 2 again; session 4
    # wrote its changes in the first run, so it isn't replayed.
    assert await asyncio.to_thread(_main, ["demo", "run"]) == 0
    out = capsys.readouterr().out
    assert (
        "Villanueva household: already loaded; 15 documents searchable in local Meko (0 new)" in out
    )
    assert "== Session 2, turn s2:t1 ==" in out
    assert any(x.startswith("Session 2: ") for x in out.splitlines())  # matched, or reported
    assert "Session 4: the changes it approves are in this database already" in out
    assert "== Session 4" not in out
    assert "Meko upkeep: 0 memories added, 0 rewritten, 0 deleted." in out


async def test_a_request_that_differs_is_reported_or_refused(
    migrated: AsyncEngine, demo_env: None, tmp_path: Path
) -> None:
    """Another machine's Meko can rank the brief's excerpts differently. Demo mode then replays the
    recorded reply and reports the call; `--strict` refuses it."""
    demo = read_demo()
    async with migrated.connect() as conn:
        household_id = await load_demo(conn, demo, through=max(c.recorded_at for c in demo.changes))
        await conn.commit()
    (session,) = [s for s in read_sessions(people=PEOPLE) if s.name == "session-2"]
    recording = json.loads(session.recording.read_text(encoding="utf-8"))
    first = next(c for c in recording["calls"] if c["key"] == "s2:t1/orchestrator/1")
    first["request_sha256"] = "0" * 64  # as if this machine's request were different
    changed = tmp_path / "session-2.json"
    changed.write_text(json.dumps(recording, ensure_ascii=False), encoding="utf-8")
    session = replace(session, recording=changed)
    settings = get_settings()

    replayed = await replay_session(migrated, settings, demo, session, household_id)
    # The planted call at least: on a machine whose Meko ranks the excerpts differently, more.
    assert "s2:t1/orchestrator/1" in replayed.drifted
    assert replayed.calls == 7
    assert [a.answer.options[0].label for a in replayed.asked] == ["A: all extra on the card"]
    with pytest.raises(RecordingError, match="'s2:t1/orchestrator/1' has changed"):
        await replay_session(migrated, settings, demo, session, household_id, strict=True)


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


async def test_session_4_approves_what_it_proposed_and_writes_the_story(
    migrated: AsyncEngine, demo_env: None, tmp_path: Path, make_settings: MakeSettings
) -> None:
    """Session 4 with the scripted model, recorded as demo mode plays it: the story is loaded
    without the rows the session writes, turn 1 proposes the new job, Mara approves it at its time
    in the story, and turn 2 is the replan. What it wrote is changes.csv rows 10 and 11."""
    demo = read_demo()
    sessions = read_sessions(people=PEOPLE)
    check_writes(sessions, demo)
    (session,) = [s for s in sessions if s.name == "session-4"]
    assert session.writes == (10, 11)
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, demo, through=max(c.recorded_at for c in demo.changes), skip=session.writes
        )
        await conn.commit()
    assert await written(migrated, demo, session, household_id) == {10: None, 11: None}
    path = tmp_path / "session-4.json"
    settings = make_settings(
        model_strong="kako-strong", model_fast="kako-fast", meko_mcp_url=get_settings().meko_mcp_url
    )
    script = {**replan_turns.turn_1(), **replan_turns.turn_2()}
    replayed = await replay_session(
        migrated,
        settings,
        demo,
        session,
        household_id,
        backend=RecordingBackend(ScriptedBackend(script), path),
    )
    told, replanned = replayed.asked
    assert [p.kind for p in told.proposed] == ["life_event", "replace_fact"]
    assert replanned.replan is not None
    assert replanned.replan.since == "the decision of Sep 15, 2026 in Session 2 (B: split)"
    found = await written(migrated, demo, session, household_id)
    assert all(key and key.startswith(str(told.session_id)) for key in found.values())
    async with migrated.connect() as conn:
        rows = list(
            await conn.execute(
                text(
                    "SELECT p.created_at, p.decided_at, s.display_name FROM proposal p "
                    "JOIN person s ON s.id = p.decided_by_person_id WHERE p.id = ANY(:ids)"
                ),
                {"ids": [p.proposal_id for p in told.proposed]},
            )
        )
    # Proposed as Kako knew it at the turn, approved by Mara at 8 PM on Nov 20, as in the story.
    assert {tuple(r) for r in rows} == {
        (
            datetime(2026, 11, 20, 19, tzinfo=MANILA),
            datetime(2026, 11, 20, 20, tzinfo=MANILA),
            "Mara",
        )
    }


async def test_a_session_that_proposes_nothing_cant_approve(
    migrated: AsyncEngine, demo_env: None, make_settings: MakeSettings
) -> None:
    demo = read_demo()
    (session,) = [s for s in read_sessions(people=PEOPLE) if s.name == "session-4"]
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, demo, through=max(c.recorded_at for c in demo.changes), skip=session.writes
        )
        await conn.commit()
    answer = {"reply": "Congratulations, Mara!", "options": [], "recommended": "", "why": ""}
    script = {"s4:t1/orchestrator/1": calls(("submit_answer", answer))}  # proposes nothing
    settings = make_settings(
        model_strong="kako-strong", model_fast="kako-fast", meko_mcp_url=get_settings().meko_mcp_url
    )
    with pytest.raises(DemoModeError, match="Session 4, turn s4:t1: nothing to approve"):
        await replay_session(
            migrated, settings, demo, session, household_id, backend=ScriptedBackend(script)
        )


async def test_demo_record_refuses_before_it_could_spend(
    migrated: AsyncEngine,
    demo_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Recording calls Foundry, so it is asked for by name, never overwrites a past run, and needs
    an empty database; none of these refusals reaches a model."""
    assert await asyncio.to_thread(_main, ["demo", "record", "session-4"]) == 1
    assert "set KAKO_MODEL_MODE=record" in capsys.readouterr().err
    monkeypatch.setenv("KAKO_MODEL_MODE", "record")
    past = tmp_path / "session-4.json"
    past.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("KAKO_RECORDED_RESPONSES", str(past))
    get_settings.cache_clear()
    assert await asyncio.to_thread(_main, ["demo", "record", "session-9"]) == 1
    assert "No session 'session-9'" in capsys.readouterr().err
    assert await asyncio.to_thread(_main, ["demo", "record", "session-4"]) == 1
    assert "exists: move it aside first" in capsys.readouterr().err
    monkeypatch.setenv("KAKO_RECORDED_RESPONSES", str(tmp_path / "new.json"))
    get_settings.cache_clear()
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo(), through=datetime(2026, 9, 15, 9, tzinfo=MANILA))
        await conn.commit()
    assert await asyncio.to_thread(_main, ["demo", "record", "session-4"]) == 1
    assert "this database holds" in capsys.readouterr().err
    assert not (tmp_path / "new.json").exists()
