"""The approvals API on Postgres: list what waits, approve it (twice changes nothing), reject, and
the refusals. Also `kako proposals` on the command line."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import Services
from kako.db.meko_log import DbCallLog
from kako.meko.adapter import Meko
from tests.conftest import MakeSettings
from tests.integration.test_proposal_store import JOB, NOV_20, House, at
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend


@asynccontextmanager
async def _api(
    engine: AsyncEngine, make_settings: MakeSettings
) -> AsyncIterator[httpx.AsyncClient]:
    settings = make_settings()

    @asynccontextmanager
    async def no_meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
        yield None

    async with httpx.AsyncClient() as http:
        services = Services(
            settings, engine, no_meko, lambda: ScriptedBackend([]), http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            yield api


pytestmark = pytest.mark.integration


async def test_list_approve_twice_and_reject(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        h = await House(conn).build()
        target = f"{h.salary}/income.monthly_net/2026-12-01"
        salary = await h.propose("replace_fact", h.new_salary(), target)
        note = await h.propose(
            "new_fact",
            {
                "entity_id": None,
                "attribute": "constraint.note",
                "value": "₱5,000 a month goes to Jun's parents",
                "valid_from": NOV_20.isoformat(),
                "valid_to": None,
                "life_event_id": None,
            },
            f"household/constraint.note/{NOV_20.isoformat()}",
            quote="₱5,000 a month goes to Jun's parents",
            source="s4:t2",
        )
    async with _api(migrated, make_settings) as api:
        pending = (await api.get("/api/v1/proposals")).json()
        assert {p["id"] for p in pending} == {str(salary), str(note)}
        shown = next(p for p in pending if p["id"] == str(salary))
        assert shown["shown"] == (
            "Mara's salary: income.monthly_net = ₱68,000.00 from Dec 1, 2026, "
            "replacing ₱52,000.00 (since Mar 1, 2026)"
        )
        assert shown["evidence"] == [
            {"kind": "turn", "ref": "conv-4:s4:t1", "quote": JOB, "said_by": "Mara"}
        ]
        # The same in parts, for the approval card: the old value struck through, then the new.
        assert shown["change"] == {
            "subject": "Mara's salary",
            "attribute": "income.monthly_net",
            "before": "₱52,000.00",
            "after": "₱68,000.00",
            "from_day": "Dec 1, 2026",
        }
        constraint = next(p for p in pending if p["id"] == str(note))["change"]
        assert (constraint["subject"], constraint["before"]) == ("Household", None)

        body = {"proposal_ids": [str(salary)], "person_id": str(h.mara)}
        first = await api.post("/api/v1/proposals/approve", json=body)
        assert first.status_code == 200, first.text
        (decided,) = first.json()
        assert (decided["status"], decided["already"]) == ("approved", False)
        again = (await api.post("/api/v1/proposals/approve", json=body)).json()
        assert again[0]["already"] is True
        assert again[0]["written"] == decided["written"]

        child = {"proposal_ids": [str(note)], "person_id": str(h.lia)}
        refused = await api.post("/api/v1/proposals/reject", json=child)
        assert refused.status_code == 409
        assert "only an adult" in refused.json()["detail"]
        rejected = await api.post(
            "/api/v1/proposals/reject", json={**child, "person_id": str(h.jun)}
        )
        assert rejected.json()[0]["status"] == "rejected"

        approved = (await api.get("/api/v1/proposals", params={"status": "approved"})).json()
        assert [(p["id"], p["decided_by"]) for p in approved] == [(str(salary), "Mara")]
        assert len((await api.get("/api/v1/proposals", params={"status": "all"})).json()) == 2


async def test_the_api_refuses(migrated: AsyncEngine, make_settings: MakeSettings) -> None:
    async with migrated.connect() as conn:
        h = await House(conn).build()
        salary = await h.propose(
            "replace_fact", h.new_salary(), f"{h.salary}/income.monthly_net/2026-12-01"
        )
    body = {"proposal_ids": [str(salary)], "person_id": str(h.mara)}
    async with _api(migrated, make_settings) as api:
        # A form posted from another site carries no JSON content type: refused, nothing written.
        form = await api.post(
            "/api/v1/proposals/approve",
            content=httpx.Request("POST", "/", json=body).content,
            headers={"content-type": "text/plain"},
        )
        assert form.status_code in (415, 422)
        missing = {**body, "proposal_ids": [str(uuid.uuid4())]}
        assert (await api.post("/api/v1/proposals/approve", json=missing)).status_code == 404
        extra = await api.post("/api/v1/proposals/approve", json={**body, "by": "Mara"})
        assert extra.status_code == 422
        too_many = {**body, "proposal_ids": [str(uuid.uuid4()) for _ in range(21)]}
        assert (await api.post("/api/v1/proposals/approve", json=too_many)).status_code == 422
        assert (await api.get("/api/v1/proposals", params={"status": "maybe"})).status_code == 422
        pending = (await api.get("/api/v1/proposals")).json()
    assert [p["id"] for p in pending] == [str(salary)]


async def test_the_command_line(
    migrated: AsyncEngine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    test_database_url: str,
) -> None:  # fmt: skip
    from kako.cli import main
    from kako.settings import get_settings

    async with migrated.connect() as conn:
        h = await House(conn).build()
        salary = await h.propose(
            "replace_fact", h.new_salary(), f"{h.salary}/income.monthly_net/2026-12-01"
        )
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    get_settings.cache_clear()

    def run(*argv: str) -> int:
        return main(list(argv))

    assert await asyncio.to_thread(run, "proposals", "list") == 0
    out = capsys.readouterr().out
    assert f"{salary} replace_fact" in out
    assert "replacing ₱52,000.00" in out
    assert f'Evidence (turn conv-4:s4:t1): Mara: "{JOB}"' in out
    assert await asyncio.to_thread(run, "proposals", "approve", str(salary), "--by", "Lia") == 1
    assert "only an adult" in capsys.readouterr().err
    assert (
        await asyncio.to_thread(
            run, "proposals", "approve", str(salary), "--by", "mara", "--no-meko"
        )
        == 0
    )
    assert f"{salary} replace_fact: approved (fact " in capsys.readouterr().out
    assert await asyncio.to_thread(run, "proposals", "approve", str(salary), "--by", "Jun") == 0
    assert "already approved; nothing changed" in capsys.readouterr().out
    assert await asyncio.to_thread(run, "proposals", "list", "--status", "approved") == 0
    assert f"approved by Mara on {at(NOV_20).year}" in capsys.readouterr().out
