"""Patterns and promotion on Postgres (Phase 4, task 4), with Meko upkeep sharing what was approved.

The demo household chose flexibility in Session 1 (Jun), Session 2 (Mara) and Session 3 (Jun). Once
Session 3 ends, dreaming proposes the preference, citing each decision, and offers Session 1's
decision for sharing (two sessions have ended since without revising it). Approving the preference
offers it for sharing at once. A promotion is approved only with its second confirmation; Meko
upkeep then promotes the preference to collective memory and uploads the decision record, and V-13
passes. The brief marks the preference promoted only as known after its sharing was approved. On
local Meko, in a datapack of its own: the same, a stopped run's promotion linked again rather than
promoted twice, and a link to a promoted memory Meko doesn't hold found by `kako meko check`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.brief_store import gather_brief
from kako.cli import main as _main
from kako.db.meko_log import DbCallLog
from kako.db.proposal_store import approve, reject
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.dreaming.job import end_session, run_dream
from kako.dreaming.promotion import propose_patterns, propose_promotions
from kako.meko.fake import FakeMeko
from kako.meko.mcp import open_meko
from kako.settings import get_settings
from kako.upkeep.check import check_links
from kako.upkeep.sync import AGENT, keep_up, keep_up_with, session_key
from tests.conftest import MakeSettings
from tests.integration.test_meko_adapter import throwaway_datapack
from tests.integration.test_proposals_api import _api
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
BEFORE_THE_PATTERN = datetime(2026, 10, 20, 12, tzinfo=MANILA)  # the story, less its row 6
DREAMT = datetime(2026, 10, 20, 21, tzinfo=MANILA)
PREFERENCE = (
    "In the Villanueva household, from Oct 18, 2026, the household's preference between paying "
    "debt off faster (speed) and keeping cash on hand (flexibility) is flexibility."
)


async def _story(conn: Any) -> tuple[uuid.UUID, dict[str, uuid.UUID], dict[str, uuid.UUID]]:
    """The demo household up to Oct 20, without the preference dreaming found then: the decisions of
    Sessions 1, 2 and 3 are the story's own. Returns the household, its people by name and its
    sessions by title."""
    demo = read_demo()
    household_id = await load_demo(conn, demo, through=BEFORE_THE_PATTERN, skip={6})
    people = {
        key: person_id
        for key, person_id in await conn.execute(
            text("SELECT lower(display_name), id FROM person WHERE household_id = :h"),
            {"h": household_id},
        )
    }
    sessions = {
        title: session_id
        for title, session_id in await conn.execute(
            text("SELECT title, id FROM session WHERE household_id = :h"), {"h": household_id}
        )
    }
    return household_id, people, sessions


async def _decision(engine: AsyncEngine, session_id: uuid.UUID) -> uuid.UUID:
    async with engine.connect() as conn:
        return (  # type: ignore[no-any-return]
            await conn.execute(
                text("SELECT id FROM decision WHERE session_id = :s"), {"s": session_id}
            )
        ).scalar_one()


async def _promotes(engine: AsyncEngine, household_id: uuid.UUID) -> dict[str, Any]:
    """The household's promote proposals, by what they share."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, payload, status FROM proposal WHERE household_id = :h "
                "AND kind = 'promote'"
            ),
            {"h": household_id},
        )
        return {next(iter(r.payload.values())): r for r in rows}


async def _promoted(engine: AsyncEngine, household_id: uuid.UUID, known_at: datetime) -> bool:
    async with engine.connect() as conn:
        _, inputs = await gather_brief(
            conn,
            None,
            household_id=household_id,
            on=date(2026, 12, 1),
            known_at=known_at,
            message="",
            conversation_id=None,
            budget=6000,
        )
    (approval,) = [
        a
        for fact_id, a in inputs.approvals.items()
        if any(
            f.id == fact_id and f.attribute == "preference.debt_vs_flexibility"
            for f in inputs.snapshot.facts
        )
    ]
    return approval.promoted


async def test_dreaming_proposes_the_preference_and_upkeep_shares_what_was_approved(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        household_id, people, sessions = await _story(conn)
    august = await _decision(migrated, sessions["Session 1"])
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")

    # Session 3 ends: its run reads no turns (the demo's session has no Meko conversation), and
    # makes steps 4 and 5 with no model and no Meko call.
    run_id = await end_session(migrated, sessions["Session 3"], DREAMT)
    meko = FakeMeko()
    report = await run_dream(migrated, meko, settings, ScriptedBackend({}), run_id, now=DREAMT)
    assert report.status == "done"
    assert (report.model_calls, meko.calls) == (0, [])
    (found,) = report.patterns
    assert (found.status, found.pattern.attribute, found.pattern.value) == (
        "proposed",
        "preference.debt_vs_flexibility",
        "flexibility",
    )
    async with migrated.connect() as conn:
        pattern = (
            await conn.execute(
                text("SELECT payload, explanation, status FROM proposal WHERE id = :p"),
                {"p": found.proposal_id},
            )
        ).one()
        evidence = list(
            await conn.execute(
                text(
                    "SELECT e.kind, e.quote, p.display_name FROM proposal_evidence e "
                    "JOIN person p ON p.id = e.person_id WHERE e.proposal_id = :p ORDER BY e.quote"
                ),
                {"p": found.proposal_id},
            )
        )
    assert pattern.status == "pending"
    assert (pattern.payload["attribute"], pattern.payload["value"]) == (
        "preference.debt_vs_flexibility",
        "flexibility",
    )
    assert pattern.payload["valid_from"] == "2026-10-18"
    assert pattern.explanation == (
        "In its decisions in Session 1, Session 2 and Session 3, the household kept cash on hand "
        "rather than paying debt off faster, and it never chose the other way."
    )
    assert [(e.kind, e.quote, e.display_name) for e in evidence] == [
        ("decision", "Keep cash for the family trip.", "Jun"),
        ("decision", "Lia starts school and we want cash on hand.", "Mara"),
        ("decision", "We'd rather have a bigger cash buffer.", "Jun"),
    ]
    # Session 1's decision has held through two sessions since: offered for sharing, once.
    offers = await _promotes(migrated, household_id)
    assert list(offers) == [str(august)]
    assert report.promotions == (offers[str(august)].id,)

    # The same decisions never propose the pattern again, and nothing is offered twice.
    async with migrated.begin() as conn:
        (again,) = await propose_patterns(conn, household_id, on=date(2026, 10, 18), now=DREAMT)
        assert (again.status, again.proposal_id) == ("already", None)
        assert await propose_promotions(conn, household_id, now=DREAMT) == []

    # A no is final: the decision is never offered again.
    async with migrated.begin() as conn:
        await reject(conn, [offers[str(august)].id], person_id=people["mara"], decided_at=DREAMT)
        assert await propose_promotions(conn, household_id, now=DREAMT) == []

    async with _api(migrated, make_settings) as api:
        # Mara approves the preference: it is offered for sharing at once.
        body = {"proposal_ids": [str(found.proposal_id)], "person_id": str(people["mara"])}
        approved = await api.post("/api/v1/proposals/approve", json=body)
        assert approved.status_code == 200, approved.text
        offers = await _promotes(migrated, household_id)
        (fact_id,) = [k for k in offers if k != str(august)]
        offer = offers[fact_id]
        assert offer.status == "pending"
        listed = (await api.get("/api/v1/proposals")).json()
        shown = next(p for p in listed if p["id"] == str(offer.id))
        assert shown["shown"] == (
            "Share the preference preference.debt_vs_flexibility = flexibility with every agent "
            "in Meko's collective memory (can't be undone)"
        )
        assert "can't be undone" in shown["explanation"]

        # The first yes isn't enough; the second confirmation is.
        body = {"proposal_ids": [str(offer.id)], "person_id": str(people["mara"])}
        once = await api.post("/api/v1/proposals/approve", json=body)
        assert once.status_code == 409
        assert "approve it again with its second confirmation" in once.json()["detail"]
        twice = await api.post(
            "/api/v1/proposals/approve", json={**body, "confirm_promotion": True}
        )
        assert twice.status_code == 200, twice.text
        assert twice.json()[0]["status"] == "approved"

    # Session 2's decision is offered once another session has ended after it.
    async with migrated.begin() as conn:
        later = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO session (id, household_id, meko_conversation_id, title, "
                "household_date, started_at, ended_at) VALUES (:i, :h, :c, 'Session 3b', "
                "'2026-10-25', :t, :t)"
            ),
            {"i": later, "h": household_id, "c": f"local-{later.hex}", "t": DREAMT},
        )
        (offered,) = await propose_promotions(conn, household_id, now=datetime.now(MANILA))
        await approve(
            conn,
            [offered],
            person_id=people["jun"],
            decided_at=datetime.now(MANILA),
            confirm_promotion=True,
        )

    # Meko upkeep: every fact's memory, the preference promoted, the decision record uploaded.
    kept = await keep_up(migrated, meko, household_id, now=datetime.now(MANILA))
    assert (kept.shared, kept.waiting, kept.problems) == (2, 0, [])
    assert [m.text for m in meko.promoted.values()] == [PREFERENCE]
    ((key, record),) = meko.documents.items()
    assert key.endswith(".md")
    assert record.text.startswith("# Decision record: How hard should we pay down the credit card?")
    assert "- A: all extra on the card: Lia starts school and we want cash on hand." in record.text
    assert await check_links(migrated, meko, household_id) == []
    assert (await keep_up(migrated, meko, household_id, now=datetime.now(MANILA))).steps == 0

    # The brief marks the preference promoted only as known once its sharing was approved: not
    # as known when the preference itself was approved, a moment before.
    assert await _promoted(migrated, household_id, datetime.now(MANILA))
    async with migrated.connect() as conn:
        approved_at = (
            await conn.execute(
                text("SELECT recorded_at FROM fact WHERE id = :f"), {"f": uuid.UUID(fact_id)}
            )
        ).scalar_one()
    assert not await _promoted(migrated, household_id, approved_at)


async def test_upkeep_shares_on_local_meko_once_and_check_finds_what_meko_doesnt_hold(
    migrated: AsyncEngine,
    test_database_url: str,
    test_meko_url: str,
    make_settings: MakeSettings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with migrated.connect() as conn:
        household_id, people, sessions = await _story(conn)
    august = await _decision(migrated, sessions["Session 1"])
    async with migrated.begin() as conn:
        (found,) = await propose_patterns(conn, household_id, on=date(2026, 10, 18), now=DREAMT)
        assert found.proposal_id is not None
        await approve(conn, [found.proposal_id], person_id=people["mara"], decided_at=DREAMT)
        offered = await propose_promotions(conn, household_id, now=DREAMT)
        assert len(offered) == 2  # the preference, and Session 1's decision
    # On the command line, too, the first yes isn't enough.
    get_settings.cache_clear()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("KAKO_DATABASE_URL", test_database_url)
        get_settings.cache_clear()
        args = ["proposals", "approve", *map(str, offered), "--by", "Mara", "--no-meko"]
        assert await asyncio.to_thread(_main, args) == 1
        assert "approve it again with its second confirmation" in capsys.readouterr().err
        assert await asyncio.to_thread(_main, [*args, "--confirm-promotion"]) == 0
        assert capsys.readouterr().out.count(" promote: approved") == 2
    get_settings.cache_clear()

    async with throwaway_datapack(test_meko_url) as datapack_id:
        settings = make_settings(meko_mcp_url=test_meko_url, meko_datapack_id=datapack_id)
        kept = await keep_up_with(migrated, settings, household_id, now=DREAMT)
        assert (kept.shared, kept.waiting, kept.problems) == (2, 0, [])
        async with migrated.connect() as conn:
            links = {
                r.kako_table: r
                for r in await conn.execute(
                    text(
                        "SELECT kako_table, kako_id, meko_id, text, agent_id FROM meko_link "
                        "WHERE meko_kind IN ('promoted_memory', 'document')"
                    )
                )
            }
        assert links["fact"].text == PREFERENCE
        assert links["fact"].agent_id == AGENT
        assert links["decision"].kako_id == august
        async with open_meko(settings, DbCallLog(migrated), max_calls=80) as meko:
            conversation = await meko.create_conversation(
                agent_id=AGENT, title="t", session_key=session_key(household_id)
            )
            promoted = await meko.promoted_memories(conversation, agent_id=AGENT)
            assert [(m.id, m.text) for m in promoted.memories] == [
                (links["fact"].meko_id, PREFERENCE)
            ]
            # Out of the memories for good: memory search no longer finds it.
            assert (
                await meko.get_memory(conversation, links["fact"].meko_id, agent_id=AGENT) is None
            )
            document = await meko.document_status(
                conversation, links["decision"].meko_id, agent_id=AGENT
            )
            assert document.state in ("indexing", "completed")
            assert await check_links(migrated, meko, household_id) == []

        # A run that stopped after promoting, before its link: the next one links the same
        # memory, and promotes nothing twice.
        async with migrated.begin() as conn:
            await conn.execute(text("DELETE FROM meko_link WHERE meko_kind = 'promoted_memory'"))
        again = await keep_up_with(migrated, settings, household_id, now=DREAMT)
        assert (again.shared, again.problems) == (1, [])
        async with migrated.connect() as conn:
            relinked = (
                await conn.execute(
                    text("SELECT meko_id FROM meko_link WHERE meko_kind = 'promoted_memory'")
                )
            ).scalar_one()
        assert relinked == links["fact"].meko_id
        assert (await keep_up_with(migrated, settings, household_id, now=DREAMT)).steps == 0

        # `kako meko check` passes, then finds a link to a promoted memory Meko doesn't hold.
        env = {
            "KAKO_DATABASE_URL": test_database_url,
            "KAKO_MEKO_DATAPACK_ID": datapack_id,
            "MEKO_MCP_URL": test_meko_url,
        }
        get_settings.cache_clear()
        with pytest.MonkeyPatch.context() as patch:
            for name, value in env.items():
                patch.setenv(name, value)
            get_settings.cache_clear()
            assert await asyncio.to_thread(_main, ["meko", "check"]) == 0
            async with migrated.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO meko_link (kako_table, kako_id, meko_kind, meko_id, "
                        "created_at, agent_id) VALUES ('fact', :f, 'promoted_memory', :m, now(), "
                        ":a)"
                    ),
                    {"f": links["fact"].kako_id, "m": str(uuid.uuid4()), "a": AGENT},
                )
            assert await asyncio.to_thread(_main, ["meko", "check"]) == 1
        get_settings.cache_clear()
