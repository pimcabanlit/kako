"""Dreaming on Postgres and local Meko (Phase 4, task 3), with a scripted model.

A session's turns kept in Meko as a planning turn keeps them; the session ends, which queues one
dreaming run; the run reads the turns back, extracts, checks, and proposes what is new as pending
proposals with its id, the quote and who said it. A rerun does nothing; a turn the session already
proposed from is never proposed twice; nothing is written until a person approves, and then the
fact says dreaming found it. The labelled set scores 100% with a careful extraction on the demo
household in Postgres, and the commands run from a recording.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import Started, start_session
from kako.agents.chat import ModelError
from kako.agents.recorded import RecordingBackend
from kako.api.app import create_app
from kako.api.sessions import Services
from kako.cli import main as _main
from kako.db.meko_log import DbCallLog
from kako.db.proposal_store import Evidence, approve, propose
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.dreaming.job import DreamError, end_session, run_dream
from kako.evals.dreaming import read_labelled, run_labelled
from kako.facts.proposals import fact_payload, fact_target, idempotency_key
from kako.meko.adapter import Meko, Turn
from kako.meko.mcp import open_meko
from kako.settings import Settings, get_settings
from tests.conftest import MakeSettings
from tests.integration.test_session_api import _probes
from tests.support.dreaming import IDEAL, ideal_script
from tests.support.models import ScriptedBackend, calls

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
NOV_20 = date(2026, 11, 20)
BEFORE_THE_JOB = datetime(2026, 11, 20, 19, tzinfo=MANILA)
ENDED = datetime(2026, 11, 20, 21, tzinfo=MANILA)
NEWS = (
    "Mara here, with news: I got a new job! I start on Dec 1, and my take-home pay will be "
    "₱68,000 a month."
)
QUOTE = "I start on Dec 1, and my take-home pay will be ₱68,000 a month."
CUT = "Jun here. Then let's cut eating out. From now on we spend ₱4,000 a month on it."
CUT_QUOTE = "From now on we spend ₱4,000 a month on it."
SALARY = {
    "entity": "income:mara-s-salary",
    "attribute": "income.monthly_net",
    "value": "68000",
    "valid_from": "2026-12-01",
}
EATING_OUT = {
    "entity": "expense:eating-out",
    "attribute": "expense.monthly_amount",
    "value": "4000",
    "valid_from": "",
}
# The facts written from dreaming's proposals (the demo story has a dreaming fact of its own).
DREAMED = "FROM fact f JOIN proposal p ON p.id = f.proposal_id WHERE p.dream_run_id IS NOT NULL"
JOB = {"kind": "new_job", "description": "Mara got a new job", "occurs_on": "2026-12-01"}


def claims() -> dict[str, Any]:
    return {
        "claims": [
            {
                "turn": "s9:t1",
                "quote": QUOTE,
                "correction": False,
                "life_event": JOB,
                "facts": [SALARY],
            },
            {
                "turn": "s9:t2",
                "quote": CUT_QUOTE,
                "correction": False,
                "life_event": None,
                "facts": [EATING_OUT],
            },
            {  # a number the household never said: refused in code, never proposed
                "turn": "s9:t2",
                "quote": CUT_QUOTE,
                "correction": False,
                "life_event": None,
                "facts": [{**EATING_OUT, "value": "3500"}],
            },
        ]
    }


def script() -> dict[str, Any]:
    return {"dream:s9:t1/extract/1": calls(("submit_claims", claims()))}


async def _people(engine: AsyncEngine, household_id: uuid.UUID) -> dict[str, uuid.UUID]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT display_name, id FROM person WHERE household_id = :h"), {"h": household_id}
        )
        return {name: pid for name, pid in rows}


def _settings(make_settings: MakeSettings, meko_url: str) -> Settings:
    return make_settings(meko_mcp_url=meko_url, model_strong="kako-strong", model_fast="kako-fast")


async def _keep(meko: Meko, session: Started, seed: str, message: str, by: uuid.UUID) -> None:
    """The turn as a planning turn keeps it in Meko (`agents.ask.trace_turn`)."""
    await meko.add_turn(
        session.conversation_id,
        Turn(
            message,
            "Noted.",
            metadata={
                "kako_turn": seed,
                "kako_session_id": str(session.session_id),
                "kako_household_id": str(session.household_id),
                "kako_household_date": session.on.isoformat(),
                "kako_said_by": str(by),
            },
            seed=seed,
        ),
        agent_id="kako:orchestrator",
    )


async def _household(engine: AsyncEngine) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    async with engine.connect() as conn:
        household_id = await load_demo(conn, read_demo(), through=BEFORE_THE_JOB)
        await conn.commit()
    return household_id, await _people(engine, household_id)


async def _session(
    engine: AsyncEngine,
    settings: Settings,
    loaded: tuple[uuid.UUID, dict[str, uuid.UUID]] | None = None,
) -> tuple[Started, dict[str, uuid.UUID]]:
    household_id, people = loaded or await _household(engine)
    async with open_meko(settings, DbCallLog(engine), max_calls=6) as meko:
        session = await start_session(
            engine, meko, household_id=household_id, on=NOV_20, title="Session 9"
        )
        await _keep(meko, session, "s9:t1", NEWS, people["Mara"])
        await _keep(meko, session, "s9:t2", CUT, people["Jun"])
        # A message that names another session isn't one of this session's turns.
        await meko.add_turn(
            session.conversation_id,
            Turn(
                "Our rent is ₱99,000 now.",
                "Noted.",
                metadata={"kako_turn": "x:t1", "kako_session_id": str(uuid.uuid4())},
                seed="x:t1",
            ),
            agent_id="kako:orchestrator",
        )
    return session, people


async def _dream(engine: AsyncEngine, settings: Settings, run_id: uuid.UUID, backend: Any) -> Any:
    async with open_meko(settings, DbCallLog(engine), max_calls=4) as meko:
        return await run_dream(engine, meko, settings, backend, run_id, now=ENDED)


async def test_dreaming_proposes_what_is_new_once_with_its_quote_and_speaker(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    settings = _settings(make_settings, test_meko_url)
    session, people = await _session(migrated, settings)
    backend = ScriptedBackend(script())
    # A session still open isn't dreamed over: its run fails, and runs again once it has ended.
    await _exec(
        migrated,
        "INSERT INTO dream_run (id, session_id, status) VALUES (gen_random_uuid(), :s, 'queued')",
        session.session_id,
    )
    early = await _scalar(
        migrated, "SELECT id FROM dream_run WHERE session_id = :s", session.session_id
    )
    with pytest.raises(DreamError, match="hasn't ended"):
        await _dream(migrated, settings, early, backend)

    run_id = await end_session(migrated, session.session_id, ENDED)
    assert await end_session(migrated, session.session_id, ENDED) == run_id  # once
    report = await _dream(migrated, settings, run_id, backend)

    assert report.ran
    assert report.status == "done"
    assert [o.outcome for o in report.outcomes] == ["new", "replace", "replace", "refused"]
    assert "not in the quote: the value ₱3,500.00" in report.outcomes[3].reason
    ((key, _, request),) = backend.requests
    assert key == "dream:s9:t1/extract/1"
    assert "₱99,000" not in request.messages[0].content  # another session's message isn't read
    assert '<data source="household">' + NEWS in request.messages[0].content

    async with migrated.connect() as conn:
        rows = list(
            await conn.execute(
                text(
                    "SELECT p.kind, p.status, p.dream_run_id, p.idempotency_key, p.created_at, "
                    "e.kind AS ekind, e.ref, e.person_id, e.quote FROM proposal p "
                    "JOIN proposal_evidence e ON e.proposal_id = p.id WHERE p.dream_run_id = :r "
                    "ORDER BY p.created_at, p.kind"
                ),
                {"r": run_id},
            )
        )
        run = (
            await conn.execute(
                text("SELECT status, started_at, finished_at, counts FROM dream_run WHERE id = :i"),
                {"i": run_id},
            )
        ).one()
    assert sorted(r.kind for r in rows) == ["life_event", "replace_fact", "replace_fact"]
    assert {r.status for r in rows} == {"pending"}
    assert {r.dream_run_id for r in rows} == {run_id}
    assert {r.created_at for r in rows} == {ENDED}
    by_kind = {r.kind: r for r in rows if r.kind == "life_event"}
    assert by_kind["life_event"].ref == f"{session.conversation_id}:s9:t1"
    assert by_kind["life_event"].person_id == people["Mara"]
    assert by_kind["life_event"].quote == QUOTE
    jun = [r for r in rows if r.person_id == people["Jun"]]
    assert [r.quote for r in jun] == [CUT_QUOTE]
    assert all(r.idempotency_key.startswith(f"{session.session_id}:s9:t") for r in rows)
    assert run.status == "done"
    assert run.counts["proposals"] == {"life_event": 1, "replace_fact": 2}
    assert run.counts["outcomes"] == {"new": 1, "refused": 1, "replace": 2}
    assert run.counts["claims"] == 3

    # A rerun does nothing: the run is done.
    again = await _dream(migrated, settings, run_id, ScriptedBackend({}))
    assert (again.ran, again.status) == (False, "done")

    # Nothing is written until a person approves; then the fact says dreaming found it.
    async with migrated.connect() as conn:
        ids = list(
            await conn.execute(
                text("SELECT id FROM proposal WHERE dream_run_id = :r ORDER BY kind"),
                {"r": run_id},
            )
        )
        before = await _count(conn, f"SELECT count(*) {DREAMED}")
        assert before == 0
        await approve(
            conn,
            [i.id for i in ids],
            person_id=people["Mara"],
            decided_at=ENDED + timedelta(hours=1),
        )
        await conn.commit()
        facts = list(
            await conn.execute(text(f"SELECT f.attribute, f.source_ref, f.source_kind {DREAMED}"))
        )
    assert sorted(f.attribute for f in facts) == ["expense.monthly_amount", "income.monthly_net"]
    assert {f.source_kind for f in facts} == {"dreaming"}
    assert {f.source_ref for f in facts} == {
        f"{session.conversation_id}:s9:t1",
        f"{session.conversation_id}:s9:t2",
    }


async def test_what_the_session_already_proposed_is_never_proposed_twice(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    settings = _settings(make_settings, test_meko_url)
    session, _ = await _session(migrated, settings)
    async with migrated.connect() as conn:
        eating_out = await _scalar(
            migrated,
            "SELECT e.id FROM entity e WHERE e.name = 'Eating out' AND e.household_id = :s",
            session.household_id,
        )
        current = await _scalar(
            migrated,
            "SELECT id FROM fact WHERE entity_id = :s AND attribute = 'expense.monthly_amount' "
            "AND status = 'active'",
            eating_out,
        )
        payload = fact_payload(
            entity_id=eating_out,
            attribute_key="expense.monthly_amount",
            value=400_000,
            valid_from=NOV_20,
            replaces=current,
        )
        await propose(
            conn,
            household_id=session.household_id,
            kind="replace_fact",
            payload=payload,
            explanation="Said in the session",
            idempotency_key=idempotency_key(
                f"{session.session_id}:s9:t2",
                "replace_fact",
                fact_target(eating_out, "expense.monthly_amount", NOV_20),
            ),
            evidence=[Evidence("turn", f"{session.conversation_id}:s9:t2", CUT_QUOTE)],
            today=NOV_20,
            created_at=ENDED - timedelta(hours=1),
        )
        await conn.commit()
    run_id = await end_session(migrated, session.session_id, ENDED)
    report = await _dream(migrated, settings, run_id, ScriptedBackend(script()))
    assert [o.outcome for o in report.outcomes] == ["new", "replace", "already", "refused"]
    assert len(report.proposed) == 2


async def test_a_failed_run_says_why_and_runs_again(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    settings = _settings(make_settings, test_meko_url)
    session, _ = await _session(migrated, settings)
    run_id = await end_session(migrated, session.session_id, ENDED)
    broken = ScriptedBackend({"dream:s9:t1/extract/1": ModelError("refused")})
    with pytest.raises(ModelError):
        await _dream(migrated, settings, run_id, broken)
    async with migrated.connect() as conn:
        run = (
            await conn.execute(
                text("SELECT status, counts FROM dream_run WHERE id = :i"), {"i": run_id}
            )
        ).one()
        assert (
            await _count(conn, "SELECT count(*) FROM proposal WHERE dream_run_id IS NOT NULL") == 0
        )
    assert run.status == "failed"
    assert "ModelError" in run.counts["error"]
    report = await _dream(migrated, settings, run_id, ScriptedBackend(script()))
    assert report.status == "done"
    assert len(report.proposed) == 3


async def test_the_labelled_set_scores_full_marks_with_a_careful_extraction(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 12, 1, 12, tzinfo=MANILA)
        )
        await conn.commit()
    cases = read_labelled()
    backend = ScriptedBackend(ideal_script({c.id: c.turns[0].seed for c in cases}))
    report = await run_labelled(
        migrated,
        make_settings(model_strong="kako-strong"),
        backend,
        cases,
        household_id=household_id,
        household_name="Villanueva household",
    )
    assert [r.error for r in report.results] == [None] * len(cases)
    assert (report.found, report.expected, report.wrong, report.unquoted) == (
        report.expected,
        sum(len(c.expect) for c in cases),
        0,
        0,
    )
    assert report.passed
    assert len(backend.requests) == len(IDEAL)


async def test_the_commands_end_a_session_and_dream_from_a_recording(
    migrated: AsyncEngine,
    test_database_url: str,
    test_meko_url: str,
    make_settings: MakeSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    settings = _settings(make_settings, test_meko_url)
    loaded = await _household(migrated)
    # Record one session's run; another session with the same words replays it.
    recorded, _ = await _session(migrated, settings, loaded)
    path = tmp_path / "dreaming.json"
    first = await end_session(migrated, recorded.session_id, ENDED)
    await _dream(migrated, settings, first, RecordingBackend(ScriptedBackend(script()), path))
    session, _ = await _session(migrated, settings, loaded)
    run_id = await end_session(migrated, session.session_id, ENDED)
    await _exec(migrated, "UPDATE session SET ended_at = NULL WHERE id = :s", session.session_id)

    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    monkeypatch.setenv("MEKO_MCP_URL", test_meko_url)
    monkeypatch.setenv("KAKO_MODEL_MODE", "replay")
    monkeypatch.setenv("KAKO_RECORDED_RESPONSES", str(path))
    get_settings.cache_clear()
    try:
        assert await asyncio.to_thread(_main, ["dream", "end", str(uuid.uuid4())]) == 1
        assert "no such session" in capsys.readouterr().err
        args = ["dream", "end", str(session.session_id), "--at", "2026-11-20T21:00:00+08:00"]
        assert await asyncio.to_thread(_main, args) == 0
        assert f"dreaming run {run_id} is queued" in capsys.readouterr().out
        assert await asyncio.to_thread(_main, ["dream", "run", "--at", ENDED.isoformat()]) == 0
        out = capsys.readouterr().out
        # The other session's new job waits for a yes already: the salary names it, and only the
        # two facts are proposed.
        assert "2 proposal(s) waiting for a yes" in out
        assert "- same: Life event (new_job) on Dec 1, 2026: Kako has it already" in out
        assert "- refused: expense:eating-out: expense.monthly_amount: not in the quote" in out
        assert await asyncio.to_thread(_main, ["dream", "run"]) == 0
        assert "No dreaming run is waiting." in capsys.readouterr().out
    finally:
        get_settings.cache_clear()


async def _exec(engine: AsyncEngine, sql: str, value: Any) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), {"s": value} if value is not None else {})


async def _scalar(engine: AsyncEngine, sql: str, value: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), {"s": value})).scalar_one()


async def _count(conn: Any, sql: str) -> int:
    return int((await conn.execute(text(sql))).scalar_one())


async def test_the_api_ends_a_session_once_and_queues_its_run(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo(), through=BEFORE_THE_JOB)
        await conn.commit()
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")

    @asynccontextmanager
    async def no_meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
        yield None

    async with httpx.AsyncClient() as http:
        services = Services(
            settings, migrated, no_meko, lambda: ScriptedBackend({}), http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            session = (
                await api.post(
                    "/api/v1/sessions", json={"title": "Session 9", "household_date": "2026-11-20"}
                )
            ).json()
            ended = await api.post(f"/api/v1/sessions/{session['id']}/end")
            again = await api.post(f"/api/v1/sessions/{session['id']}/end")
            turn = await api.post(
                f"/api/v1/sessions/{session['id']}/turns", json={"message": NEWS, "seed": "t1"}
            )
            unknown = await api.post(f"/api/v1/sessions/{uuid.uuid4()}/end")

    assert ended.status_code == 200, ended.text
    body = ended.json()
    assert (body["session_id"], body["dream_status"]) == (session["id"], "queued")
    assert again.json() == body  # once: the same end and the same run
    assert turn.status_code == 409
    assert "the session has ended" in turn.text
    assert unknown.status_code == 404
