"""What the plan screen reads (Phase 5, task 2), on Postgres with the scripted model.

Session 4 through the API (Mara's news, her approval, Jun's question) proposes a plan. Its "why"
goes down to the rows: every figure an option cites with its formula in words, the figures and
facts it was built from, all present; each fact with where it came from; what the number check
matched; the household's words and who said them. What changed is the replan's diff against the
decision the household last made (Session 3), with the three decisions to revisit; a later plan is
compared with this one.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import Services
from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.meko.adapter import Meko
from tests.conftest import MakeSettings
from tests.integration.test_replan import ASK, MANILA, NEWS, T1, T2, _people, turn_1, turn_2
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _no_meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
    yield None


async def test_the_plan_and_its_why(migrated: AsyncEngine, make_settings: MakeSettings) -> None:
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
            none_yet = (await api.get("/api/v1/plans")).json()
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
            listed = (await api.get("/api/v1/plans")).json()
            plan_id = asked.json()["plan"]["id"]
            plan = (await api.get(f"/api/v1/plans/{plan_id}")).json()

            # A later plan (another version on the same figures) is compared with this one.
            later = await _copy_plan(migrated, uuid.UUID(plan_id))
            again = (await api.get(f"/api/v1/plans/{later}")).json()

            missing = await api.get(f"/api/v1/plans/{uuid.uuid4()}")
            elsewhere = await api.get(
                f"/api/v1/plans/{plan_id}", params={"household_id": str(uuid.uuid4())}
            )
            bad = await api.get("/api/v1/plans/not-a-plan")

    assert none_yet == []
    assert [(p["version"], p["status"], p["session_title"], p["options"]) for p in listed] == [
        (1, "proposed", "Session 4", 2)
    ]
    assert listed[0]["as_of"] == "2026-12-01"  # the replan's date: the new job's first day
    head = plan["plan"]
    assert head == listed[0]
    answer = asked.json()
    assert plan["summary"] == answer["reply"]

    # The options as the turn offered them, the recommended one marked.
    assert [o["label"] for o in plan["options"]] == [o["label"] for o in answer["options"]]
    assert [o["recommended"] for o in plan["options"]] == [
        o["label"] == head["recommended_option"] for o in plan["options"]
    ]
    for option, shown in zip(plan["options"], answer["options"], strict=True):
        assert option["summary"] == shown["summary"]
        assert {(a["name"], a["centavos"]) for a in option["allocations"]} == {
            (a["name"], a["centavos"]) for a in shown["allocations"]
        }

    # Why, down to the rows: every cited figure, every figure it was built from and every fact
    # any of them read is in the plan's maps, and each formula is in words.
    figures, facts = plan["figures"], plan["facts"]
    cited = [f for o in plan["options"] for f in o["why"]["figures"]]
    assert cited, "each option cites the figures that show it"
    for figure in figures.values():
        assert figure["formula_words"] != figure["formula"]
        assert set(figure["inputs"]) <= set(figures)
        assert set(figure["facts"]) <= set(facts)
    assert set(cited) <= set(figures)
    stored = await _figure_values(migrated, list(figures))
    for figure_id, figure in figures.items():
        assert stored[figure_id] == figure["formula"]
    what_ifs = {figures[f]["what_if"] for f in cited}
    assert all(w and "₱" in w for w in what_ifs)  # each option's figures come from its what-if

    sources = {f["source"] for f in facts.values()}
    assert "From the household's starting figures" in sources
    assert any(s.startswith("From a statement, approved by ") for s in sources)
    balance = next(f for f in facts.values() if f["title"] == "Credit card (balance)")
    assert balance["value"] == "₱76,880.00"  # November's statement
    assert balance["replaced"] == "₱81,000.00"  # October's, kept

    for option in plan["options"]:
        for words in option["why"]["words"]:  # the household's own words, when cited
            assert words == {"quote": ASK, "said_by": "Jun"}
        assert option["checks"], "each option's texts passed the number check"
        for check in option["checks"]:
            assert check["result"] == "pass"
            assert all(n["matched"] for n in check["numbers"])

    # The turn that proposed it; Meko was off, so no calls and no trace.
    turn = plan["turn"]
    assert (turn["seed"], turn["said_by"], turn["message"]) == (T2, "Jun", ASK)
    assert (turn["in_meko"], turn["trace_url"], turn["meko_calls"]) == (False, None, [])

    # What changed: against the decision of Oct 18, as the replan said.
    changed = plan["changed"]
    assert changed["since"] == answer["replan"]["since"]
    assert changed["since_plan"] is None
    assert changed["figures"][0] == {
        "title": "Take-home pay a month, all incomes",
        "before": "₱100,000.00",
        "after": "₱116,000.00",
        "headline": True,
    }
    assert {
        "label": "replaced",
        "title": "Mara's salary (take-home pay a month)",
        "before": "₱52,000.00",
        "after": "₱68,000.00",
        "from_day": "Dec 1, 2026",
    } in changed["facts"]
    assert len(changed["revisit"]) == 3
    assert {r["session_title"] for r in changed["revisit"]} == {
        "Session 1",
        "Session 2",
        "Session 3",
    }
    for revisit in changed["revisit"]:
        assert [b["title"] for b in revisit["because"]] == ["Mara's salary (take-home pay a month)"]

    # The next version is compared with this one: the same figures, so nothing moved.
    assert again["plan"]["version"] == 2
    assert again["changed"]["since"] == "plan v1 of Dec 1, 2026"
    assert again["changed"]["since_plan"] == plan_id
    assert (again["changed"]["figures"], again["changed"]["facts"]) == ([], [])

    assert missing.status_code == 404
    assert elsewhere.status_code == 404
    assert bad.status_code == 422


async def _figure_values(engine: AsyncEngine, ids: list[str]) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id::text, formula FROM figure WHERE id::text = ANY(:ids)"), {"ids": ids}
        )
        return {r[0]: r[1] for r in rows}


async def _copy_plan(engine: AsyncEngine, plan_id: uuid.UUID) -> uuid.UUID:
    """Another version of the household's plan on the same run, as a later turn would make."""
    new_id = uuid.uuid4()
    async with engine.begin() as conn:
        row: Any = (
            (await conn.execute(text("SELECT * FROM plan WHERE id = :id"), {"id": plan_id}))
            .mappings()
            .one()
        )
        await conn.execute(
            text(
                "INSERT INTO plan (id, household_id, version, session_id, calc_run_id, status, "
                "summary, created_at) VALUES (:id, :household, 2, :session, :run, 'proposed', "
                "'Again.', :at)"
            ),
            {
                "id": new_id,
                "household": row["household_id"],
                "session": row["session_id"],
                "run": row["calc_run_id"],
                "at": datetime.now(UTC),
            },
        )
    return new_id
