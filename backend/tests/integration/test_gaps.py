"""Context Gaps on Postgres (Phase 4, task 6), with Meko's search log in memory (`FakeMeko`).

A planning search for who looks after Lia after school finds nothing: kept as an open gap with its
band, score and question, once. Mara's note answers it; once approved and written into Meko by
upkeep, the search is replayed after the approval and goes from low to `improved`, with both scores
stored. Before then it waits; a replay Meko is still indexing waits for the next run; a run replays
at most five. The refusals, `kako gaps`, and local Meko, which serves no self-learning tools: there
nothing changes and the commands say why.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import Services
from kako.cli import main as _main
from kako.db.meko_log import DbCallLog
from kako.db.proposal_store import approve, reject
from kako.gaps.store import (
    MAX_REPLAYS,
    GapError,
    answer_gap,
    collect_gaps,
    dismiss_gap,
    list_gaps,
    verify_gaps,
)
from kako.meko.adapter import Meko, SelfLearningUnavailable
from kako.meko.fake import FakeMeko
from kako.meko.mcp import open_meko
from kako.settings import get_settings
from kako.upkeep.sync import keep_up
from tests.conftest import MakeSettings
from tests.integration.test_meko_adapter import throwaway_datapack
from tests.integration.test_proposal_store import NOV_20, House, at
from tests.integration.test_proposals_api import _probes
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration

ASKED = "Who looks after Lia after school?"
NOTE = "Lola Remy looks after Lia after school."
PLANNER = "kako:orchestrator"


@asynccontextmanager
async def _api(
    engine: AsyncEngine, make_settings: MakeSettings, meko: Meko | None
) -> AsyncIterator[httpx.AsyncClient]:
    settings = make_settings()

    @asynccontextmanager
    async def opened(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
        yield meko

    async with httpx.AsyncClient() as http:
        services = Services(
            settings, engine, opened, lambda: ScriptedBackend([]), http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            yield api


async def _searched(meko: FakeMeko, *queries: str) -> None:
    """Planning turns' searches, as Meko logs them."""
    conversation = await meko.create_conversation(agent_id=PLANNER, title="Session 4")
    for query in queries:
        await meko.search_context(conversation, query, agent_id=PLANNER)


async def _note(h: House, words: str = NOTE, source: str = "s4:t2") -> uuid.UUID:
    payload = {
        "entity_id": None,
        "attribute": "constraint.note",
        "value": words,
        "valid_from": NOV_20.isoformat(),
        "valid_to": None,
        "life_event_id": None,
    }
    target = f"household/constraint.note/{NOV_20.isoformat()}/{source}"
    return await h.propose("new_fact", payload, target, quote=words, source=source)


async def test_a_weak_search_answered_goes_from_low_to_improved(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        h = await House(conn).build()
        meko = FakeMeko()
        await keep_up(migrated, meko, h.id, now=at(NOV_20))  # the seed's facts, in Meko
        await _searched(meko, ASKED, "Mara's salary")

        # The weak search is kept once, with its band, its score and a question; the strong one
        # isn't a gap.
        (made,) = await collect_gaps(migrated, meko, h.id)
        assert await collect_gaps(migrated, meko, h.id) == []
        (gap,) = await list_gaps(conn, h.id)
        assert (gap.id, gap.query, gap.band_before, gap.score_before, gap.reason, gap.status) == (
            made,
            ASKED,
            "low",
            Decimal("0.000"),  # nothing came back
            "weak_match",
            "open",
        )
        assert gap.question == (
            f'Kako looked for "{ASKED}" in what it knows about your household and found little '
            "to go on. Can you tell Kako about it?"
        )
        note = await _note(h)
        await conn.commit()

    async with _api(migrated, make_settings, meko) as api:
        # Mara's note answers it; nothing is replayed while it waits for a yes.
        answered = await api.post(f"/api/v1/gaps/{made}/answer", json={"proposal_id": str(note)})
        assert answered.status_code == 200, answered.text
        assert (answered.json()["status"], answered.json()["proposal_id"]) == (
            "answered",
            str(note),
        )
        report = await verify_gaps(migrated, meko, h.id)
        assert (report.replayed, report.waiting, report.verified) == (0, 1, [])
        assert "selflearning_verify" not in meko.calls

        # The approval writes the note; upkeep gives it a memory; then the search is replayed.
        body = {"proposal_ids": [str(note)], "person_id": str(h.mara)}
        approved = await api.post("/api/v1/proposals/approve", json=body)
        assert approved.status_code == 200, approved.text
        assert meko.calls.count("selflearning_verify") == 1
        (shown,) = (await api.get("/api/v1/gaps", params={"status": "verified"})).json()
        assert shown["id"] == str(made)
        assert (shown["verify_outcome"], shown["band_before"]) == ("improved", "low")
        assert Decimal(shown["score_before"]) == Decimal("0.000")
        assert Decimal(shown["score_after"]) == Decimal("0.800")  # all but "who", in the note
        assert (await api.get("/api/v1/gaps", params={"status": "open"})).json() == []

        # Verified is final: nothing replays it again, and it isn't dismissed.
        assert (await verify_gaps(migrated, meko, h.id)).replayed == 0
        refused = await api.post(f"/api/v1/gaps/{made}/dismiss", json={"person_id": str(h.jun)})
        assert refused.status_code == 409
    async with migrated.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT score_before, score_after, verify_outcome FROM context_gap")
            )
        ).one()
    assert tuple(stored) == (Decimal("0.000"), Decimal("0.800"), "improved")


async def test_a_replay_waits_for_upkeep_and_for_indexing_and_a_run_is_bounded(
    migrated: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with migrated.connect() as conn:
        h = await House(conn).build()
        meko = FakeMeko()
        asked = [f"Who looks after Lia after school on day {n}?" for n in range(MAX_REPLAYS + 2)]
        await _searched(meko, *asked)
        made = await collect_gaps(migrated, meko, h.id)
        assert len(made) == MAX_REPLAYS + 2
        note = await _note(h, NOTE + " On every day 0 to 6.")
        for gap_id in made:
            await answer_gap(conn, h.id, gap_id, note)
        await approve(conn, [note], person_id=h.mara, decided_at=at(NOV_20, 13))
        await conn.commit()

    # Approved, but upkeep hasn't written its memory yet.
    report = await verify_gaps(migrated, meko, h.id)
    assert (report.replayed, report.waiting) == (0, MAX_REPLAYS + 2)
    await keep_up(migrated, meko, h.id, now=at(NOV_20, 14))

    # Meko is still indexing: each replay waits, with nothing stored.
    real = meko.replay_search

    async def indexing(*args: Any, **kw: Any) -> Any:
        return replace(await real(*args, **kw), indexing=True)

    monkeypatch.setattr(meko, "replay_search", indexing)
    report = await verify_gaps(migrated, meko, h.id)
    assert (report.replayed, report.waiting, report.verified) == (
        MAX_REPLAYS,
        MAX_REPLAYS + 2,
        [],
    )
    async with migrated.connect() as conn:
        assert {g.verify_outcome for g in await list_gaps(conn, h.id)} == {None}
    monkeypatch.setattr(meko, "replay_search", real)

    # At most five a run; the next run replays the rest.
    first = await verify_gaps(migrated, meko, h.id)
    assert (first.replayed, len(first.verified), first.waiting) == (MAX_REPLAYS, MAX_REPLAYS, 2)
    second = await verify_gaps(migrated, meko, h.id)
    assert (second.replayed, len(second.verified), second.waiting) == (2, 2, 0)
    async with migrated.connect() as conn:
        assert {g.status for g in await list_gaps(conn, h.id)} == {"verified"}


async def test_what_a_gap_refuses(migrated: AsyncEngine, make_settings: MakeSettings) -> None:
    async with migrated.connect() as conn:
        h = await House(conn).build()
        other = await House(conn).build()
        meko = FakeMeko()
        await _searched(meko, ASKED, "What does Jun's car loan cost?")
        first, second = await collect_gaps(migrated, meko, h.id)
        assert await collect_gaps(migrated, meko, other.id) == []  # logged once: kept once
        retract = await h.propose(
            "retract_fact",
            {"fact_id": str(h.card_balance), "reason": "paid off"},
            f"{h.card_balance}/retract",
            quote="The card is paid off.",
        )
        rejected = await _note(h, "Lola Remy picks Lia up.", source="s4:t3")
        await reject(conn, [rejected], person_id=h.mara, decided_at=at(NOV_20, 13))
        theirs = await _note(other)
        pending = await _note(h, "Lola Remy picks Lia up at four.", source="s4:t4")
        await conn.commit()
        for proposal, why in (
            (retract, "an answer is a proposal that writes a fact"),
            (rejected, "the proposal is rejected"),
            (theirs, "no such proposal in this household"),
        ):
            with pytest.raises(GapError, match=why):
                await answer_gap(conn, h.id, first, proposal)
            await conn.rollback()
        with pytest.raises(GapError, match="no such gap"):
            await answer_gap(conn, other.id, first, theirs)
        await conn.rollback()
        with pytest.raises(GapError, match="only an adult"):
            await dismiss_gap(conn, h.id, first, h.lia)
        await conn.rollback()
        with pytest.raises(GapError, match="only an adult"):
            await dismiss_gap(conn, h.id, first, other.mara)
        await conn.rollback()

    mine = {"household_id": str(h.id)}
    async with _api(migrated, make_settings, meko) as api:
        dismissed = await api.post(
            f"/api/v1/gaps/{first}/dismiss", json={"person_id": str(h.jun), **mine}
        )
        assert dismissed.json().get("status") == "dismissed", dismissed.text
        again = await api.post(
            f"/api/v1/gaps/{first}/answer", json={"proposal_id": str(pending), **mine}
        )
        assert again.status_code == 409  # dismissed: not answered
        assert "dismissed" in again.json()["detail"]
        child = await api.post(
            f"/api/v1/gaps/{second}/dismiss", json={"person_id": str(h.lia), **mine}
        )
        assert child.status_code == 403
        missing = await api.post(
            f"/api/v1/gaps/{uuid.uuid4()}/answer", json={"proposal_id": str(theirs), **mine}
        )
        assert missing.status_code == 404
        # A JSON body posted as text/plain from another site: refused, nothing changed.
        form = await api.post(
            f"/api/v1/gaps/{second}/dismiss",
            content=httpx.Request("POST", "/", json={"person_id": str(h.jun), **mine}).content,
            headers={"content-type": "text/plain"},
        )
        assert form.status_code in (415, 422)
        listed = {g["id"]: g["status"] for g in (await api.get("/api/v1/gaps", params=mine)).json()}
        assert listed == {str(first): "dismissed", str(second): "open"}
        extra = await api.post(
            f"/api/v1/gaps/{second}/dismiss",
            json={"person_id": str(h.jun), "status": "verified", **mine},
        )
        assert extra.status_code == 422


async def test_where_meko_serves_no_self_learning_nothing_changes(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        h = await House(conn).build()
        meko = FakeMeko()
        await _searched(meko, ASKED)
        (gap,) = await collect_gaps(migrated, meko, h.id)
        note = await _note(h)
        await answer_gap(conn, h.id, gap, note)
        await conn.commit()
    meko.self_learning = False
    with pytest.raises(SelfLearningUnavailable):
        await collect_gaps(migrated, meko, h.id)
    async with _api(migrated, make_settings, meko) as api:
        synced = await api.post("/api/v1/gaps/sync", json={})
        assert synced.status_code == 503
        assert "self-learning" in synced.json()["detail"]
        # The approval and upkeep go ahead; the replay doesn't, and the gap waits.
        body = {"proposal_ids": [str(note)], "person_id": str(h.mara)}
        assert (await api.post("/api/v1/proposals/approve", json=body)).status_code == 200
        (shown,) = (await api.get("/api/v1/gaps")).json()
        assert (shown["status"], shown["verify_outcome"]) == ("answered", None)
    assert "memory_add" in meko.calls


async def test_the_commands_and_local_meko(
    migrated: AsyncEngine,
    make_settings: MakeSettings,
    test_database_url: str,
    test_meko_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with migrated.connect() as conn:
        h = await House(conn).build()
        meko = FakeMeko()
        await _searched(meko, ASKED, "What does Jun's car loan cost?")
        first, second = await collect_gaps(migrated, meko, h.id)
        note = await _note(h)

    async with throwaway_datapack(test_meko_url) as datapack_id:
        # Local Meko has no self-learning tools: the adapter says so.
        settings = make_settings(meko_mcp_url=test_meko_url, meko_datapack_id=datapack_id)
        async with open_meko(settings, DbCallLog(migrated), max_calls=1) as local:
            with pytest.raises(SelfLearningUnavailable, match="Meko Cloud does"):
                await local.logged_searches("none", agent_id="kako:gaps", band="low")

        env = {
            "KAKO_DATABASE_URL": test_database_url,
            "MEKO_MCP_URL": test_meko_url,
            "KAKO_MEKO_DATAPACK_ID": datapack_id,
        }
        with pytest.MonkeyPatch.context() as patch:
            for name, value in env.items():
                patch.setenv(name, value)
            get_settings.cache_clear()
            run = asyncio.to_thread
            assert await run(_main, ["gaps", "list"]) == 0
            assert f"{first} [open] low" in capsys.readouterr().out
            assert await run(_main, ["gaps", "answer", str(first), str(note)]) == 0
            assert await run(_main, ["gaps", "dismiss", str(second), "--by", "Lia"]) == 1
            assert "only an adult" in capsys.readouterr().err
            assert await run(_main, ["gaps", "dismiss", str(second), "--by", "Jun"]) == 0
            assert await run(_main, ["gaps", "list", "--status", "answered"]) == 0
            listed = capsys.readouterr().out
            assert f"Answered by proposal {note}" in listed
            assert "1 gap(s)." in listed
            assert await run(_main, ["gaps", "sync"]) == 1
            assert "Meko Cloud does" in capsys.readouterr().err
            # Approving the answer runs upkeep on local Meko, then says the replay can't run.
            assert await run(_main, ["proposals", "approve", str(note), "--by", "Mara"]) == 0
            out = capsys.readouterr().out
            assert "Meko upkeep:" in out
            assert "this Meko can't replay searches" in out
            assert await run(_main, ["gaps", "verify"]) == 1
        get_settings.cache_clear()
    async with migrated.connect() as conn:
        statuses = {g.id: g.status for g in await list_gaps(conn, h.id)}
    assert statuses == {first: "answered", second: "dismissed"}
