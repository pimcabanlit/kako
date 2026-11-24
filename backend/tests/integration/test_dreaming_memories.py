"""Meko's extracted memories as dreaming's candidates, on Postgres and local Meko (Phase 4, task 3).

Local Meko doesn't extract on its own (docs/meko-setup.md, spike 4), so the test writes the
memories Meko Cloud would: sentences in the session's conversation, with no `kako_` metadata. The
run shows them to extraction as noted memories; each settles to exactly one fate. One a claim says
the same as waits for the household's yes and is then linked to what they approved; one with a
number the household didn't say, or one no claim names, is deleted from Meko; a memory Kako wrote
itself is never touched. V-14 (`check_extracted`) passes at each step, and finds a memory Meko
extracted after the run.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.cli import main as _main
from kako.db.meko_log import DbCallLog
from kako.db.proposal_store import Evidence, ProposalError, approve, propose, reject
from kako.dreaming.job import end_session
from kako.dreaming.memories import check_extracted, settle_memories
from kako.facts.proposals import life_event_payload
from kako.meko.adapter import Meko
from kako.meko.mcp import open_meko
from kako.settings import Settings, get_settings
from tests.conftest import MakeSettings
from tests.integration.test_dreaming import (
    ENDED,
    NOV_20,
    _dream,
    _scalar,
    _session,
    _settings,
    claims,
)
from tests.support.models import ScriptedBackend, calls

pytestmark = pytest.mark.integration

AGENT = "kako:orchestrator"  # the conversation's agent, as Meko's extraction would write it
SAME = "Mara starts a new job on December 1 with take-home pay of 68,000 pesos a month."
EXTRA = "Jun wants the household to spend 4,000 pesos a month on eating out, down from 5,000."
LOOSE = "The household is relieved and happy about Mara's new job."
KAKOS = "Mara Villanueva's take-home pay was ₱52,000.00 a month."
LATE = "Mara's new job is at a company in Makati with a new job title."


def named_script() -> dict[str, Any]:
    """The session's claims, naming the noted memories (m1: EXTRA, m2: SAME, m3: LOOSE)."""
    found = claims()
    found["claims"][0]["memories"] = ["m2"]
    found["claims"][1]["memories"] = ["m1", "m9"]  # m9: no such memory, dropped
    return {"dream:s9:t1/extract/1": calls(("submit_claims", found))}


async def _memories(meko: Meko, conversation_id: str) -> dict[str, str]:
    found = await meko.search_memories(
        conversation_id, f"{SAME} {EXTRA} {LOOSE} {KAKOS} {LATE}", agent_id="kako:test", limit=20
    )
    return {m.text: m.id for m in found}


async def _extracted(settings: Settings, engine: AsyncEngine, conversation_id: str) -> None:
    async with open_meko(settings, DbCallLog(engine), max_calls=4) as meko:
        for sentence in (SAME, EXTRA, LOOSE):
            await meko.add_memory(conversation_id, sentence, {}, agent_id=AGENT)
        await meko.add_memory(
            conversation_id, KAKOS, {"kako_source": "approved_fact"}, agent_id=AGENT
        )


async def _settle(settings: Settings, engine: AsyncEngine) -> Any:
    async with open_meko(settings, DbCallLog(engine), max_calls=22) as meko:
        return await settle_memories(engine, meko, now=ENDED + timedelta(hours=2))


async def _check(settings: Settings, engine: AsyncEngine) -> list[str]:
    async with open_meko(settings, DbCallLog(engine), max_calls=4) as meko:
        return await check_extracted(engine, meko)


async def _run(
    engine: AsyncEngine, settings: Settings
) -> tuple[Any, uuid.UUID, Any, ScriptedBackend]:
    session, _ = await _session(engine, settings)
    await _extracted(settings, engine, session.conversation_id)
    run_id = await end_session(engine, session.session_id, ENDED)
    backend = ScriptedBackend(named_script())
    report = await _dream(engine, settings, run_id, backend)
    return session, run_id, report, backend


async def _proposals(engine: AsyncEngine, run_id: uuid.UUID, turn: str) -> list[uuid.UUID]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT DISTINCT p.id FROM proposal p JOIN proposal_evidence e "
                "ON e.proposal_id = p.id WHERE p.dream_run_id = :r AND e.ref LIKE :t"
            ),
            {"r": run_id, "t": f"%:{turn}"},
        )
        return [r.id for r in rows]


async def test_each_extracted_memory_ends_linked_or_deleted(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    settings = _settings(make_settings, test_meko_url)
    session, run_id, report, backend = await _run(migrated, settings)

    # Extraction saw Meko's three memories as data, never Kako's own.
    ((_, _, request),) = backend.requests
    brief = request.messages[0].content or ""
    assert f'- m1: <data source="meko">{EXTRA}</data>' in brief
    assert f'- m2: <data source="meko">{SAME}</data>' in brief
    assert f'- m3: <data source="meko">{LOOSE}</data>' in brief
    assert KAKOS not in brief
    fates = {c.noted.text: (c.fate, c.reason) for c in report.candidates}
    assert fates[SAME][0] == "waiting"
    assert fates[EXTRA] == ("delete", "it holds a number the household didn't say: 5000")
    assert fates[LOOSE] == ("delete", "no claim says the same as it")

    # The proposals Mara's words made show Meko's memory, without it holding any of their numbers.
    async with migrated.connect() as conn:
        shown = list(
            await conn.execute(
                text(
                    "SELECT p.kind, e.quote FROM proposal p JOIN proposal_evidence e "
                    "ON e.proposal_id = p.id WHERE p.dream_run_id = :r "
                    "AND e.kind = 'extracted_memory'"
                ),
                {"r": run_id},
            )
        )
    assert sorted(r.kind for r in shown) == ["life_event", "replace_fact"]
    assert {r.quote for r in shown} == {SAME}

    # Settling deletes the two from Meko; the one waiting and Kako's own stay.
    settled = await _settle(settings, migrated)
    assert (settled.linked, settled.deleted, settled.waiting, settled.problems) == (0, 2, 1, [])
    async with open_meko(settings, DbCallLog(migrated), max_calls=2) as meko:
        left = await _memories(meko, session.conversation_id)
    assert set(left) == {SAME, KAKOS}
    assert await _check(settings, migrated) == []

    # Mara approves her news: the memory is linked to the life event and the fact it wrote.
    mara = await _scalar(
        migrated, "SELECT id FROM person WHERE display_name = 'Mara' AND household_id = :s",
        session.household_id,
    )  # fmt: skip
    async with migrated.connect() as conn:
        await approve(
            conn,
            await _proposals(migrated, run_id, "s9:t1"),
            person_id=mara,
            decided_at=ENDED + timedelta(hours=1),
        )
        await conn.commit()
    settled = await _settle(settings, migrated)
    assert (settled.linked, settled.deleted) == (1, 0)
    async with migrated.connect() as conn:
        links = sorted(
            r.kako_table
            for r in await conn.execute(
                text(
                    "SELECT kako_table FROM meko_link WHERE meko_id = :m AND meko_kind = 'memory'"
                ),
                {"m": left[SAME]},
            )
        )
        state = (
            await conn.execute(text("SELECT counts FROM dream_run WHERE id = :r"), {"r": run_id})
        ).scalar_one()["memories"]
    assert links == ["fact", "life_event"]
    assert sorted(m["state"] for m in state) == ["deleted", "deleted", "linked"]
    assert await _check(settings, migrated) == []
    again = await _settle(settings, migrated)  # nothing left to do
    assert (again.linked, again.deleted, again.waiting) == (0, 0, 0)

    # A memory Meko extracted after the run is found by the check.
    async with open_meko(settings, DbCallLog(migrated), max_calls=1) as meko:
        late = await meko.add_memory(session.conversation_id, LATE, {}, agent_id=AGENT)
    assert await _check(settings, migrated) == [
        f"run {run_id}: memory {late} wasn't dreamed over (Meko extracted it after the run)"
    ]


async def test_a_memory_whose_proposals_are_rejected_is_deleted(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    settings = _settings(make_settings, test_meko_url)
    session, run_id, _, _ = await _run(migrated, settings)
    await _settle(settings, migrated)
    jun = await _scalar(
        migrated, "SELECT id FROM person WHERE display_name = 'Jun' AND household_id = :s",
        session.household_id,
    )  # fmt: skip
    async with migrated.connect() as conn:
        await reject(
            conn,
            await _proposals(migrated, run_id, "s9:t1"),
            person_id=jun,
            decided_at=ENDED + timedelta(hours=1),
        )
        await conn.commit()
    # Decided but not settled: the check says so; settling deletes it.
    (problem,) = await _check(settings, migrated)
    assert "was decided but not settled" in problem
    settled = await _settle(settings, migrated)
    assert (settled.linked, settled.deleted, settled.problems) == (0, 1, [])
    async with open_meko(settings, DbCallLog(migrated), max_calls=2) as meko:
        assert set(await _memories(meko, session.conversation_id)) == {KAKOS}
    assert await _check(settings, migrated) == []
    async with migrated.connect() as conn:
        linked = await conn.execute(text("SELECT count(*) FROM meko_link"))
        assert linked.scalar_one() == 0


async def test_meko_words_never_hold_a_number_for_v09(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    settings = _settings(make_settings, test_meko_url)
    session, _ = await _session(migrated, settings)
    async with migrated.connect() as conn:
        with pytest.raises(ProposalError, match="V-09"):
            await propose(
                conn,
                household_id=session.household_id,
                kind="life_event",
                payload=life_event_payload(
                    event_id=uuid.uuid4(),
                    kind="big_expense",
                    description="A ₱35,000 laptop",
                    occurs_on=NOV_20,
                    source_ref=f"{session.conversation_id}:s9:t2",
                ),
                explanation="Said in the session",
                idempotency_key=f"{session.session_id}:s9:t2|life_event|x",
                evidence=[
                    Evidence("turn", f"{session.conversation_id}:s9:t2", "We bought a laptop."),
                    Evidence("extracted_memory", str(uuid.uuid4()), "A laptop for ₱35,000."),
                ],
                today=NOV_20,
                created_at=ENDED,
            )


async def test_the_commands_settle_and_check(
    migrated: AsyncEngine,
    test_database_url: str,
    test_meko_url: str,
    make_settings: MakeSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(make_settings, test_meko_url)
    session, run_id, _, _ = await _run(migrated, settings)
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    monkeypatch.setenv("MEKO_MCP_URL", test_meko_url)
    get_settings.cache_clear()
    try:
        assert await asyncio.to_thread(_main, ["dream", "settle"]) == 0
        assert "0 linked, 2 deleted, 1 waiting." in capsys.readouterr().out
        assert await asyncio.to_thread(_main, ["dream", "check"]) == 0
        assert "V-14 passes" in capsys.readouterr().out
        async with open_meko(settings, DbCallLog(migrated), max_calls=1) as meko:
            late = await meko.add_memory(session.conversation_id, LATE, {}, agent_id=AGENT)
        assert await asyncio.to_thread(_main, ["dream", "check"]) == 1
        assert f"V-14: run {run_id}: memory {late} wasn't dreamed over" in capsys.readouterr().out
    finally:
        get_settings.cache_clear()
