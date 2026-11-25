"""Before and after a plan's options through the API (Phase 5a, item 5), on Postgres with the
scripted model.

Session 4 through the API proposes a plan with two options. `GET /api/v1/plans/{id}/compare` takes
the turn's snapshot again exactly (its hash is the stored run's), runs each option's allocations on
it, and sets each beside today's plan: what each reaches, what it changes, and its months one by
one. Another household's plan and an unknown one are 404; a turn whose snapshot can't be taken again
as it was is 409, never a comparison on different facts.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import Services
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from tests.conftest import MakeSettings
from tests.integration.test_plans_api import _no_meko
from tests.integration.test_replan import ASK, MANILA, NEWS, T1, T2, _people, turn_1, turn_2
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration


async def test_each_option_beside_today(migrated: AsyncEngine, make_settings: MakeSettings) -> None:
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 11, 20, 19, tzinfo=MANILA)
        )
        await conn.commit()
    people = await _people(migrated, household_id)
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    script = {**turn_1(), **turn_2()}
    async with httpx.AsyncClient() as http:
        services = Services(
            settings, migrated, _no_meko, lambda: ScriptedBackend(script), http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            session = (
                await api.post(
                    "/api/v1/sessions", json={"title": "Session 4", "household_date": "2026-11-20"}
                )
            ).json()
            turns = f"/api/v1/sessions/{session['id']}/turns"
            told = await api.post(
                turns, json={"message": NEWS, "seed": T1, "person_id": str(people["Mara"])}
            )
            await api.post(
                "/api/v1/proposals/approve",
                json={
                    "proposal_ids": [c["proposal_id"] for c in told.json()["changes"]],
                    "person_id": str(people["Mara"]),
                },
            )
            asked = await api.post(
                turns, json={"message": ASK, "seed": T2, "person_id": str(people["Jun"])}
            )
            assert asked.status_code == 200, asked.text
            plan_id = asked.json()["plan"]["id"]
            plan = (await api.get(f"/api/v1/plans/{plan_id}")).json()
            found = await api.get(f"/api/v1/plans/{plan_id}/compare")
            again = await api.get(f"/api/v1/plans/{plan_id}/compare")

            missing = await api.get(f"/api/v1/plans/{uuid.uuid4()}/compare")
            elsewhere = await api.get(
                f"/api/v1/plans/{plan_id}/compare", params={"household_id": str(uuid.uuid4())}
            )
            await _tamper(migrated, uuid.UUID(plan_id))
            changed = await api.get(f"/api/v1/plans/{plan_id}/compare")

    assert found.status_code == 200, found.text
    c = found.json()
    assert again.json() == c  # read again, the same: nothing is written, nothing random
    assert c["plan_id"] == plan_id
    assert c["as_of"] == "2026-12-01"
    assert c["baseline"].startswith("Today's plan on Dec 1, 2026: ")

    # The options in the plan's order, each with what it puts in each month.
    labels = [o["label"] for o in plan["options"]]
    assert [o["label"] for o in c["options"]] == labels
    for head, option in zip(c["options"], plan["options"], strict=True):
        for a in option["allocations"]:
            if a["centavos"]:
                assert f"{a['shown']} to the {a['name']}" in head["each_month"]
    assert c["baseline"] == (
        "Today's plan on Dec 1, 2026: ₱4,000.00 a month to the Credit card and ₱5,050.00 a month "
        "to the Emergency fund, with ₱16,000.00 a month not yet planned."
    )
    assert [o["each_month"] for o in c["options"]] == [
        "₱25,050.00 a month to the Credit card and nothing to the Emergency fund",
        "₱10,000.00 a month to the Credit card and ₱15,050.00 a month to the Emergency fund",
    ]
    cells = {r["label"]: [(o["value"], o["change"]) for o in r["options"]] for r in c["rows"]}
    assert cells["Credit card paid off"] == [
        ("Mar 1, 2027", "12 months sooner"),
        ("Jul 1, 2027", "8 months sooner"),
    ]
    assert cells["Emergency fund at its target"] == [
        ("never", "never reached"),
        ("Apr 1, 2027", "6 months sooner"),
    ]

    # Every outcome has today's value and one cell for each option, with its change in words.
    assert len(c["rows"]) >= 5
    for row in c["rows"]:
        assert len(row["options"]) == len(labels)
        assert row["before"]["change"] is None
        assert row["before"]["direction"] == "none"
        for cell in row["options"]:
            assert cell["direction"] in ("better", "worse", "same", "none")
            if cell["direction"] in ("better", "worse", "same"):
                assert cell["change"]
    kinds = [r["kind"] for r in c["rows"]]
    assert kinds[-1] == "unplanned"
    assert {"debt_paid", "emergency_fund"} <= set(kinds)
    assert any(r["on_card"] for r in c["rows"])

    # Month by month for each option: each open debt beside today's plan, its totals adding up.
    assert [m["label"] for m in c["months"]] == labels
    for months in c["months"]:
        assert months["debts"], months
        for debt in months["debts"]:
            assert debt["rows"]
            assert [r["month"] for r in debt["rows"]] == list(range(1, len(debt["rows"]) + 1))
            assert all(0.0 <= r["fill"] <= 1.0 for r in debt["rows"])
            assert debt["closing"]
            assert debt["before_closing"]
            if debt["paid_off"] is not None:
                assert debt["rows"][-1]["left"] == "₱0.00"
                assert _pesos(debt["paid_total"]) == _pesos(debt["principal_total"]) + _pesos(
                    debt["interest_total"]
                )
        fund = months["fund"]
        if fund is not None:
            assert fund["rows"][-1]["to_go"] is None or len(fund["rows"]) == 120

    assert missing.status_code == 404
    assert elsewhere.status_code == 404
    assert changed.status_code == 409
    assert "can't be compared" in changed.json()["detail"]


def _pesos(text_: str) -> int:
    return int(text_.replace("₱", "").replace(",", "").replace(".", ""))


async def _tamper(engine: AsyncEngine, plan_id: uuid.UUID) -> None:
    """Make the turn's stored run name a snapshot the facts no longer give."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE calc_run SET snapshot_hash = 'not-the-snapshot' "
                "WHERE id = (SELECT calc_run_id FROM plan WHERE id = :id)"
            ),
            {"id": plan_id},
        )
