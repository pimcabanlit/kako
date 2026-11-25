"""What the session screen reads, on Postgres with the scripted model (Phase 5, task 1).

A turn taken through the API is kept as the household saw it (`session_turn`), with who wrote it as
a participant; the household's sessions list it, newest first; the session's turns give back the
same answer with the agents' steps; a turn running now shows its steps as they come; and the
household names its people for the "writing as" picker, adults first.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import Probes, create_app
from kako.api.sessions import Running, Services
from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.health import MekoStatus, ServiceStatus
from kako.meko.adapter import Meko
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend
from tests.test_agents_turn import SEED, SESSION_2
from tests.test_agents_turn import _session_2_script as script

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))


def _probes() -> Probes:
    async def up() -> ServiceStatus:
        return ServiceStatus(ok=True, detail="test", latency_ms=0, version=None)

    async def meko() -> MekoStatus:
        return MekoStatus(ok=True, detail="test", latency_ms=0, version=None, target="local")

    return Probes(postgres=up, meko=meko)


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(text(sql), params)]


@asynccontextmanager
async def _no_meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
    yield None  # Meko off: the session has no conversation, and the screen still reads it all


async def test_a_turn_kept_and_read_back(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo(), through=datetime(2026, 9, 15, 9, tzinfo=MANILA))
        await conn.commit()
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    async with httpx.AsyncClient(timeout=30) as http:
        services = Services(
            settings, migrated, _no_meko, lambda: ScriptedBackend(script()), http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            household = (await api.get("/api/v1/household")).json()
            people = {p["display_name"]: p for p in household["people"]}
            mara = people["Mara"]["id"]

            created = await api.post("/api/v1/sessions", json={"title": "Paying down the card"})
            assert created.status_code == 201, created.text
            session_id = created.json()["id"]
            listed_before = (await api.get("/api/v1/sessions")).json()
            empty = (await api.get(f"/api/v1/sessions/{session_id}/turns")).json()

            turn = await api.post(
                f"/api/v1/sessions/{session_id}/turns",
                json={"message": SESSION_2, "seed": SEED, "person_id": mara},
            )
            assert turn.status_code == 200, turn.text
            answer = turn.json()
            listed = (await api.get("/api/v1/sessions")).json()
            read = (await api.get(f"/api/v1/sessions/{session_id}/turns")).json()

            # A turn running now: its steps so far, and none once it is kept.
            services.running = Running(
                uuid.UUID(session_id), "t9", "And the house fund?", None, datetime.now(UTC)
            )
            live = (await api.get(f"/api/v1/sessions/{session_id}/turns")).json()["running"]
            services.running = Running(
                uuid.UUID(session_id), SEED, SESSION_2, None, datetime.now(UTC)
            )
            kept_now = (await api.get(f"/api/v1/sessions/{session_id}/turns")).json()["running"]
            services.running = None

            missing = await api.get(f"/api/v1/sessions/{uuid.uuid4()}/turns")
            other = await api.get("/api/v1/household", params={"household_id": str(uuid.uuid4())})

    # The household and its people, adults first: who may write and who may approve.
    assert household["name"]
    assert [(p["display_name"], p["role"]) for p in household["people"]] == [
        ("Jun", "adult"),
        ("Mara", "adult"),
        ("Lia", "child"),
    ]
    assert other.status_code == 404

    # The sessions list: the demo's own sessions and the new one, the most recently active first.
    assert listed_before[0]["id"] == session_id
    assert listed_before[0]["turns"] == 0
    assert empty["turns"] == []
    assert empty["running"] is None
    assert listed[0]["id"] == session_id
    assert (listed[0]["title"], listed[0]["turns"]) == ("Paying down the card", 1)
    assert listed[0]["last_at"] >= listed[0]["started_at"]
    assert all(s["turns"] == 0 for s in listed[1:])  # the demo's past sessions: no turns kept

    # The turn read back: the household's words, who wrote them, and exactly the answer shown then.
    assert read["session"]["id"] == session_id
    assert read["session"]["ended_at"] is None
    [kept] = read["turns"]
    assert kept["seed"] == SEED
    assert kept["message"] == SESSION_2
    assert kept["said_by"] == {"id": mara, "display_name": "Mara"}
    assert kept["answer"] == answer
    assert [o["label"] for o in answer["options"]] == ["A: all extra on the card", "B: split"]
    # Each allocation names its entity as the household wrote it, beside the stable ref.
    assert {(a["entity"], a["name"]) for a in answer["options"][1]["allocations"]} == {
        ("debt:credit-card", "Credit card"),
        ("account:emergency-fund", "Emergency fund"),
    }

    # The agents' steps, as `agent_step` logged them, in the turn's own order.
    steps = await _rows(
        migrated,
        "SELECT seq, agent, tool, outcome FROM agent_step "
        "WHERE session_id = :s AND meko_turn_seed = :t ORDER BY seq",
        s=session_id,
        t=SEED,
    )
    assert steps
    assert [(s["seq"], s["agent"], s["tool"], s["outcome"]) for s in kept["steps"]] == steps
    assert {s["agent"] for s in kept["steps"]} >= {"orchestrator", "debt", "savings"}

    assert live == {
        "seed": "t9",
        "said_by": None,
        "message": "And the house fund?",
        "started_at": live["started_at"],
        "steps": [],
    }
    assert kept_now is None  # the running seed is already kept: shown once, as a turn
    assert missing.status_code == 404

    # Postgres: one row for the turn, written once, and Mara a participant of the session.
    assert await _rows(
        migrated,
        "SELECT meko_turn_seed, said_by::text, message FROM session_turn WHERE session_id = :s",
        s=session_id,
    ) == [(SEED, mara, SESSION_2)]
    assert await _rows(
        migrated,
        "SELECT person_id::text FROM session_participant WHERE session_id = :s",
        s=session_id,
    ) == [(mara,)]
