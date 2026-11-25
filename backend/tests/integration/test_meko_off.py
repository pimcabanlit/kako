"""Kako with Meko off (`KAKO_MEKO_OFF`), on Postgres with the scripted model: what a laptop with no
Meko to reach runs.

The real services, built from settings, open no Meko at all. A new session is kept in Kako only;
session 4 runs through the API as it does with Meko (Mara's news proposed, approved with no Meko
upkeep, Jun's question answered with a plan), and its options are compared. Meko's own screens say
Meko is off (503, which the web app shows as a note), and a session kept in Meko can't take a turn
here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import services_from
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from tests.conftest import MakeSettings
from tests.integration.test_replan import ASK, MANILA, NEWS, T1, T2, _people, turn_1, turn_2
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration


async def test_the_app_runs_with_meko_off(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 11, 20, 19, tzinfo=MANILA)
        )
        await conn.commit()
    people = await _people(migrated, household_id)
    # Meko's address is a closed port: anything that reached for it would fail.
    settings = make_settings(
        model_strong="kako-strong",
        model_fast="kako-fast",
        meko_off=True,
        meko_mcp_url="http://127.0.0.1:9/mcp",
    )
    script = {**turn_1(), **turn_2()}
    async with httpx.AsyncClient() as http:
        services = services_from(settings, migrated, http)
        services.backend = lambda: ScriptedBackend(script)
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            made = await api.post(
                "/api/v1/sessions", json={"title": "Trying Kako", "household_date": "2026-11-20"}
            )
            assert made.status_code == 201, made.text
            session = made.json()
            turns = f"/api/v1/sessions/{session['id']}/turns"
            told = await api.post(
                turns, json={"message": NEWS, "seed": T1, "person_id": str(people["Mara"])}
            )
            assert told.status_code == 200, told.text
            approved = await api.post(
                "/api/v1/proposals/approve",
                json={
                    "proposal_ids": [c["proposal_id"] for c in told.json()["changes"]],
                    "person_id": str(people["Jun"]),
                },
            )
            asked = await api.post(
                turns, json={"message": ASK, "seed": T2, "person_id": str(people["Jun"])}
            )
            assert asked.status_code == 200, asked.text
            plan_id = asked.json()["plan"]["id"]
            compared = await api.get(f"/api/v1/plans/{plan_id}/compare")
            kept = (await api.get(turns)).json()
            trace = (await api.get(f"/api/v1/sessions/{session['id']}/trace")).json()
            meko_metrics = await api.get("/api/v1/metrics/meko")
            gaps = await api.post("/api/v1/gaps/sync", json={})

            # A session kept in Meko (made elsewhere) can't take a turn while Meko is off.
            await _keep_in_meko(migrated, uuid.UUID(session["id"]))
            refused = await api.post(turns, json={"message": "And now?", "seed": "t3"})

    assert session["meko_conversation_id"] is None  # kept in Kako only
    assert approved.status_code == 200, approved.text
    assert all(a["status"] == "approved" for a in approved.json())
    assert asked.json()["replan"] is not None
    assert compared.status_code == 200, compared.text
    assert [len(t["steps"]) > 0 for t in kept["turns"]] == [True, True]
    assert trace["source"] == "none"
    assert meko_metrics.status_code == 503
    assert "Meko is off here" in meko_metrics.json()["detail"]
    assert gaps.status_code == 503
    assert "Meko is off here" in gaps.json()["detail"]
    assert refused.status_code == 409
    assert "start a new session" in refused.json()["detail"]
    async with migrated.connect() as conn:
        calls = (await conn.execute(text("SELECT count(*) FROM meko_call"))).scalar_one()
    assert calls == 0  # not one call to Meko


async def _keep_in_meko(engine: AsyncEngine, session_id: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE session SET meko_conversation_id = 'conv-elsewhere' WHERE id = :id"),
            {"id": session_id},
        )
