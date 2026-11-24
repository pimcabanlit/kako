"""A turn end to end through the session API, on Postgres and local Meko, with the scripted model.

Phase 3, task 6, done when: one turn on local Meko leaves a conversation turn, a plan,
recommendations with sources, and a trace with the session's Meko calls as spans.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import Probes, create_app
from kako.api.sessions import Services
from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.health import MekoStatus, ServiceStatus
from kako.meko.adapter import Meko
from kako.meko.mcp import open_meko
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend
from tests.test_agents_turn import SEED, SESSION_2
from tests.test_agents_turn import _session_2_script as script

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(text(sql), params)]


async def test_a_turn_through_the_api_on_local_meko(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo(), through=datetime(2026, 9, 15, 9, tzinfo=MANILA))
        await conn.commit()
    settings = make_settings(
        meko_mcp_url=test_meko_url, model_strong="kako-strong", model_fast="kako-fast"
    )

    @asynccontextmanager
    async def meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
        async with open_meko(settings, log, max_calls=max_calls) as adapter:
            yield adapter

    async with httpx.AsyncClient(timeout=30) as trace_http:
        services = Services(
            settings, migrated, meko, lambda: ScriptedBackend(script()), trace_http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://kako") as api:
            created = await api.post(
                "/api/v1/sessions", json={"title": "Session 2", "household_date": "2026-09-15"}
            )
            assert created.status_code == 201, created.text
            session = created.json()
            conversation = session["meko_conversation_id"]
            assert conversation
            try:
                turn = await api.post(
                    f"/api/v1/sessions/{session['id']}/turns",
                    json={"message": SESSION_2, "seed": SEED},
                )
                assert turn.status_code == 200, turn.text
                answer = turn.json()
                trace = (await api.get(f"/api/v1/sessions/{session['id']}/trace")).json()
                again = await api.post(
                    f"/api/v1/sessions/{session['id']}/turns",
                    json={"message": SESSION_2, "seed": SEED},
                )
                missing = await api.post(
                    f"/api/v1/sessions/{uuid.uuid4()}/turns", json={"message": "hi"}
                )
                async with services.turn_lock:  # a turn running: another is refused, not queued
                    busy = await api.post(
                        f"/api/v1/sessions/{session['id']}/turns", json={"message": "hi"}
                    )
                async with open_meko(settings, DbCallLog(migrated)) as reader:
                    kept = await reader.read_turns(conversation, agent_id="kako:orchestrator")
            finally:
                async with open_meko(settings, DbCallLog(migrated)) as cleaner:
                    await cleaner.delete_conversation(conversation, agent_id="kako:orchestrator")

    # The answer: options A and B with their allocations and sources; the conflict left to the
    # household; nothing flagged; a proposed plan.
    assert [o["label"] for o in answer["options"]] == ["A: all extra on the card", "B: split"]
    b = answer["options"][1]
    assert {(x["entity"], x["shown"]) for x in b["allocations"]} == {
        ("debt:credit-card", "₱4,000.00"),
        ("account:emergency-fund", "₱5,050.00"),
    }
    assert {s["kind"] for s in b["sources"]} >= {"figure", "conversation"}
    assert answer["resolution"]["conflicts"] == ["over-allocation"]
    assert answer["resolution"]["chosen"] is None
    assert answer["flagged"] == []
    plan = answer["plan"]
    assert plan["version"] == 1
    assert answer["meko"]["message_id"]
    assert answer["meko"]["error"] is None
    assert answer["cost"]["model_calls"] == 6
    assert again.status_code == 409  # the same seed is the same turn: never run twice
    assert missing.status_code == 404
    assert busy.status_code == 429

    # Postgres: the plan, a recommendation per option and entity with its sources (a figure and
    # something else, V-11), the conflict, and each check tied to what it checked.
    [(status, summary, version)] = await _rows(
        migrated, "SELECT status, summary, version FROM plan WHERE id = :p", p=plan["id"]
    )
    assert (status, summary, version) == ("proposed", answer["reply"], 1)
    recs = await _rows(
        migrated,
        "SELECT r.option, r.allocation, "
        "count(*) FILTER (WHERE s.source_kind = 'figure'), "
        "count(*) FILTER (WHERE s.source_kind <> 'figure') "
        "FROM recommendation r JOIN recommendation_source s ON s.recommendation_id = r.id "
        "WHERE r.plan_id = :p GROUP BY r.id ORDER BY r.option, r.allocation",
        p=plan["id"],
    )
    assert [(o, c) for o, c, _, _ in recs] == [
        ("A: all extra on the card", 0),
        ("A: all extra on the card", 905_000),
        ("B: split", 400_000),
        ("B: split", 505_000),
    ]
    assert all(figures >= 1 and others >= 1 for _, _, figures, others in recs)
    [rec_ids] = [o["recommendation_ids"] for o in answer["options"] if o["label"] == "B: split"]
    assert len(rec_ids) == 2
    # Every figure a source names is a stored figure of the turn's run or one of its what-ifs.
    [(dangling,)] = await _rows(
        migrated,
        "SELECT count(*) FROM recommendation_source s JOIN recommendation r "
        "ON r.id = s.recommendation_id LEFT JOIN figure f ON f.id::text = s.source_id "
        "WHERE r.plan_id = :p AND s.source_kind = 'figure' AND f.id IS NULL",
        p=plan["id"],
    )
    assert dangling == 0
    [(kind, figure_count, rejected)] = await _rows(
        migrated,
        "SELECT kind, cardinality(figure_ids), rejected FROM reconciliation WHERE plan_id = :p",
        p=plan["id"],
    )
    assert (kind, figure_count, rejected) == ("over_allocation", 2, None)
    subjects = await _rows(
        migrated,
        "SELECT subject, subject_id IS NOT NULL FROM number_check WHERE session_id = :s "
        "ORDER BY created_at",
        s=session["id"],
    )
    assert subjects[2:] == [
        ("reply", True),
        *[("recommendation", True)] * 4,
        ("reconciliation", True),
    ]
    # Each what-if the tools ran is a scenario with its overrides, and its step names its run.
    steps = await _rows(
        migrated,
        "SELECT a.calc_run_id IS NOT NULL, count(o.id) FROM agent_step a "
        "LEFT JOIN calc_run c ON c.id = a.calc_run_id "
        "LEFT JOIN scenario_override o ON o.scenario_id = c.scenario_id "
        "WHERE a.session_id = :s AND a.tool = 'run_what_if' GROUP BY a.id",
        s=session["id"],
    )
    assert steps
    assert all(linked and overrides >= 1 for linked, overrides in steps)

    # Meko: the conversation holds the turn, with the steps, the reasoning and Kako's ids.
    [message] = kept
    assert message.input == SESSION_2
    assert message.output == answer["reply"]
    assert len(message.plan) == 4
    assert message.plan[2].startswith("Reconciled their proposals in code (over-allocation)")
    assert "debt specialist:" in (message.reasoning or "")
    assert message.metadata["kako_plan_id"] == plan["id"]
    assert message.metadata["kako_turn"] == SEED
    assert message.metadata["kako_recommendation_ids"]["B: split"] == rec_ids

    # The trace: every Meko call made with the conversation, each a span, the same calls Kako
    # counted in meko_call for the session.
    assert trace["source"] == "local_call_log"
    spans = trace["spans"]
    assert [s["tool"] for s in spans] == [
        "conversation_create",
        "context_search",
        "conversation_add_message",
    ]
    assert all(s["ok"] for s in spans)
    [search] = [s for s in spans if s["tool"] == "context_search"]
    assert search["parts"]  # the search's own parts, each a span of its own in the call log
    counted = await _rows(
        migrated,
        "SELECT tool FROM meko_call WHERE session_id = :s ORDER BY created_at",
        s=session["id"],
    )
    assert [t for (t,) in counted] == [s["tool"] for s in spans]
    assert json.dumps(trace)  # plain JSON all the way


def _probes() -> Probes:
    async def ok() -> ServiceStatus:
        return ServiceStatus(ok=True, detail="test")

    async def meko_ok() -> MekoStatus:
        return MekoStatus(ok=True, detail="test", target="local")

    return Probes(postgres=ok, meko=meko_ok)
