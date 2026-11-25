"""Meko upkeep on Postgres and local Meko (Phase 4, task 5), in a datapack of its own.

The demo household's facts each get one memory in Kako's words. When Mara's new job replaces her
salary, the old memory is rewritten in the past tense and the new one added, so a memory search for
"Mara's salary" finds the current value and the old one in the past tense (the task's done-when).
A retraction deletes its memory and brings the old salary back to the present tense. A memory Meko
extracted, linked to the salary, is deleted once the salary is replaced. V-13 (`kako meko check`)
passes after each run, and finds a link to a memory Meko no longer holds.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.brief_store import _recap_memories
from kako.cli import main as _main
from kako.db.fact_store import load_facts
from kako.db.meko_log import DbCallLog
from kako.db.proposal_store import Evidence, approve, propose
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.facts.proposals import fact_payload, fact_target, idempotency_key, retract_payload
from kako.meko.mcp import open_meko
from kako.settings import Settings, get_settings
from kako.upkeep.check import check_links
from kako.upkeep.sync import AGENT, keep_up_with, session_key
from tests.conftest import MakeSettings
from tests.integration.test_brief_store import _session_with_turns
from tests.integration.test_meko_adapter import throwaway_datapack

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
BEFORE_THE_NEWS = datetime(2026, 11, 20, 19, 0, tzinfo=MANILA)
NEWS = datetime(2026, 11, 20, 20, 0, tzinfo=MANILA)
NEW_SALARY = (
    "In the Villanueva household, from Dec 1, 2026, Mara's salary (take-home pay a month) "
    "is ₱68,000.00."
)
OLD_SALARY_NOW = (
    "In the Villanueva household, from Mar 1, 2026, Mara's salary (take-home pay a month) "
    "is ₱52,000.00."
)
OLD_SALARY_PAST = (
    "In the Villanueva household, from Mar 1, 2026 until Nov 30, 2026, Mara's salary "
    "(take-home pay a month) was ₱52,000.00."
)


async def _ids(engine: AsyncEngine, household_id: uuid.UUID) -> dict[str, uuid.UUID]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT name, id FROM entity WHERE household_id = :h"),
            {"h": household_id},
        )
        return {name: row_id for name, row_id in rows}


async def _people(engine: AsyncEngine, household_id: uuid.UUID) -> dict[str, uuid.UUID]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT display_name, id FROM person WHERE household_id = :h"),
            {"h": household_id},
        )
        return {name: row_id for name, row_id in rows}


async def _salary(engine: AsyncEngine, household_id: uuid.UUID, mara_salary: uuid.UUID) -> Any:
    async with engine.connect() as conn:
        facts = await load_facts(conn, household_id)
    return next(
        f
        for f in facts
        if f.entity_id == mara_salary
        and f.attribute == "income.monthly_net"
        and f.status != "retracted"
        and f.valid_to is None
    )


async def _decide(
    engine: AsyncEngine,
    household_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any],
    target: str,
    quote: str,
    by: uuid.UUID,
    at: datetime,
) -> None:
    async with engine.connect() as conn:
        proposed = await propose(
            conn,
            household_id=household_id,
            kind=kind,
            payload=payload,
            explanation="Mara's news",
            idempotency_key=idempotency_key(f"test:{uuid.uuid4().hex[:8]}", kind, target),
            evidence=[Evidence("turn", "s4:t1", quote, by)],
            today=date(2026, 11, 20),
            created_at=at,
        )
        await approve(conn, [proposed.proposal_id], person_id=by, decided_at=at)
        await conn.commit()


async def _find(
    settings: Settings, engine: AsyncEngine, household_id: uuid.UUID, query: str
) -> list[str]:
    async with open_meko(settings, DbCallLog(engine), max_calls=2) as meko:
        conversation_id = await meko.create_conversation(
            agent_id=AGENT, title="test", session_key=session_key(household_id)
        )
        found = await meko.find_memories(conversation_id, query, agent_id="kako:test", limit=10)
    return [m.text for m in found]


async def _check(settings: Settings, engine: AsyncEngine, household_id: uuid.UUID) -> list[str]:
    async with open_meko(settings, DbCallLog(engine), max_calls=80) as meko:
        return await check_links(engine, meko, household_id)


async def _links(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT coalesce(agent_id, '-'), count(*) FROM meko_link GROUP BY 1")
        )
        return {agent: n for agent, n in rows}


async def test_meko_keeps_each_fact_and_the_old_salary_in_the_past_tense(
    migrated: AsyncEngine, test_database_url: str, test_meko_url: str, make_settings: MakeSettings
) -> None:
    demo = read_demo()
    async with migrated.connect() as conn:
        household_id = await load_demo(conn, demo, through=BEFORE_THE_NEWS)
        await conn.commit()
        live = (
            await conn.execute(
                text("SELECT count(*) FROM fact WHERE household_id = :h AND status <> 'retracted'"),
                {"h": household_id},
            )
        ).scalar_one()
    ids = await _ids(migrated, household_id)
    people = await _people(migrated, household_id)
    async with throwaway_datapack(test_meko_url) as datapack_id:
        settings = make_settings(meko_mcp_url=test_meko_url, meko_datapack_id=datapack_id)

        # Every fact gets its memory; the statements replaced in November are in the past tense.
        first = await keep_up_with(migrated, settings, household_id, now=BEFORE_THE_NEWS)
        assert (first.added, first.rewritten, first.deleted, first.waiting) == (live, 0, 0, 0)
        assert first.problems == []
        assert await _links(migrated) == {AGENT: live}
        assert await _check(settings, migrated, household_id) == []
        again = await keep_up_with(migrated, settings, household_id, now=BEFORE_THE_NEWS)
        assert again.steps == 0  # nothing owed
        found = await _find(settings, migrated, household_id, "Mara's salary")
        assert OLD_SALARY_NOW in found

        # A memory Meko extracted from Mara's words, linked to her old salary once approved.
        old = await _salary(migrated, household_id, ids["Mara's salary"])
        async with open_meko(settings, DbCallLog(migrated), max_calls=2) as meko:
            conversation_id = await meko.create_conversation(
                agent_id="kako:orchestrator", title="s"
            )
            extracted = await meko.add_memory(
                conversation_id,
                "Mara earns 52,000 pesos a month.",
                {},
                agent_id="kako:orchestrator",
            )
        async with migrated.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO meko_link (kako_table, kako_id, meko_kind, meko_id, created_at, "
                    "agent_id) VALUES ('fact', :f, 'memory', :m, now(), 'kako:orchestrator')"
                ),
                {"f": old.id, "m": extracted},
            )
        assert (await keep_up_with(migrated, settings, household_id, now=NEWS)).steps == 0

        # Mara's new job replaces her salary from Dec 1.
        await _decide(
            migrated,
            household_id,
            "replace_fact",
            fact_payload(
                entity_id=ids["Mara's salary"],
                attribute_key="income.monthly_net",
                value=6_800_000,
                valid_from=date(2026, 12, 1),
                replaces=old.id,
            ),
            fact_target(ids["Mara's salary"], "income.monthly_net", date(2026, 12, 1)),
            "I start on Dec 1, and my take-home pay will be ₱68,000 a month.",
            people["Mara"],
            NEWS,
        )
        replaced = await keep_up_with(migrated, settings, household_id, now=NEWS)
        assert (replaced.added, replaced.rewritten, replaced.deleted) == (1, 1, 1)
        found = await _find(settings, migrated, household_id, "Mara's salary")
        assert NEW_SALARY in found
        assert OLD_SALARY_PAST in found  # the done-when: the current value and the old one
        assert OLD_SALARY_NOW not in found
        assert "Mara earns 52,000 pesos a month." not in found  # Meko's words are gone
        assert await _check(settings, migrated, household_id) == []

        # She misread the offer: the new salary is retracted, and the old one holds again.
        new = await _salary(migrated, household_id, ids["Mara's salary"])
        await _decide(
            migrated,
            household_id,
            "retract_fact",
            retract_payload(new.id, "Mara misread the offer"),
            f"fact/{new.id}",
            "Sorry, I misread the offer.",
            people["Mara"],
            NEWS + timedelta(hours=1),
        )
        retracted = await keep_up_with(migrated, settings, household_id, now=NEWS)
        assert (retracted.added, retracted.rewritten, retracted.deleted) == (0, 1, 1)
        found = await _find(settings, migrated, household_id, "Mara's salary")
        assert NEW_SALARY not in found
        assert OLD_SALARY_NOW in found
        assert await _check(settings, migrated, household_id) == []

        # The commands: nothing left to do, and the check passes; then a memory deleted behind
        # Kako's back is found.
        get_settings.cache_clear()
        env = {"KAKO_MEKO_DATAPACK_ID": datapack_id, "MEKO_MCP_URL": test_meko_url}
        with pytest.MonkeyPatch.context() as patch:
            for name, value in env.items():
                patch.setenv(name, value)
            patch.setenv("KAKO_DATABASE_URL", test_database_url)
            get_settings.cache_clear()
            assert await asyncio.to_thread(_main, ["meko", "sync"]) == 0
            assert await asyncio.to_thread(_main, ["meko", "check"]) == 0
            async with open_meko(settings, DbCallLog(migrated), max_calls=2) as meko:
                conversation_id = await meko.create_conversation(
                    agent_id=AGENT, title="t", session_key=session_key(household_id)
                )
                (gone, *_) = await _link_ids(migrated)
                await meko.delete_memory(conversation_id, gone, agent_id=AGENT)
            assert await asyncio.to_thread(_main, ["meko", "check"]) == 1
        get_settings.cache_clear()


async def _link_ids(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT meko_id FROM meko_link ORDER BY meko_id"))
        return [r for (r,) in rows]


async def test_an_ended_session_is_recapped_once_as_kakos_own_memory(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    """A session's recap, written by code from its kept turns, goes to Meko once it has ended:
    one memory as `kako:upkeep`, linked to the session, found by a later search, and marked as
    Kako's recap by the brief (docs/data-model.md, "What Kako keeps in Meko")."""
    async with migrated.connect() as conn:
        household_id = await load_demo(conn, read_demo(), through=BEFORE_THE_NEWS)
        people = {
            name: person
            for name, person in await conn.execute(
                text("SELECT display_name, id FROM person WHERE household_id = :h"),
                {"h": household_id},
            )
        }
        session_id = await _session_with_turns(
            conn,
            household_id,
            [
                (people["Jun"], "What if I lose my job?", "Kako can show your runway instead."),
                (people["Jun"], "Just give me the simulation", "Here is the runway."),
            ],
            title="Jun's worry",
            topics={2: ("Jun's job and the household's runway", None)},
        )
        await conn.commit()
    async with throwaway_datapack(test_meko_url) as datapack_id:
        settings = make_settings(meko_mcp_url=test_meko_url, meko_datapack_id=datapack_id)

        # Not ended yet: no recap is owed.
        first = await keep_up_with(migrated, settings, household_id, now=NEWS)
        assert first.recapped == 0
        assert first.problems == []
        assert await _check(settings, migrated, household_id) == []

        async with migrated.begin() as conn:
            await conn.execute(
                text("UPDATE session SET ended_at = :t WHERE id = :s"),
                {"t": NEWS, "s": session_id},
            )
        assert await _check(settings, migrated, household_id) == [
            f"session {session_id}: ended, its recap not in Meko yet (kako meko sync)"
        ]

        ended = await keep_up_with(migrated, settings, household_id, now=NEWS)
        assert (ended.recapped, ended.added, ended.problems) == (1, 0, [])
        async with migrated.connect() as conn:
            (memory_id, agent, written), *others = list(
                await conn.execute(
                    text(
                        "SELECT meko_id, agent_id, text FROM meko_link "
                        "WHERE kako_table = 'session' AND kako_id = :s"
                    ),
                    {"s": session_id},
                )
            )
            marked = await _recap_memories(conn, household_id, [memory_id, "not-a-recap"])
        assert others == []
        assert agent == AGENT
        assert written.startswith("In the Villanueva household, Jun's worry (Dec 1, 2026): ")
        assert "Just give me the simulation" in written
        assert marked == {memory_id}
        assert written in await _find(settings, migrated, household_id, "Jun's job runway")
        assert await _check(settings, migrated, household_id) == []

        # Written once: a recap is the session as it ended.
        assert (await keep_up_with(migrated, settings, household_id, now=NEWS)).steps == 0
