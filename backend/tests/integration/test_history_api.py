"""What the timeline and decisions screens read (Phase 5, task 3), on the demo household.

Loaded through Nov 20, 8:30 PM, Mara's new job is approved but starts on Dec 1: the timeline lists
it ahead of the household's date with the salary it replaces, her ₱52,000 still current and
₱68,000 coming; the three decisions of Sessions 1 to 3 each rest on her old salary, so each is
to revisit, with every option it didn't choose and why. Loaded through Oct 20, nothing is to
revisit yet.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import Services
from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.meko.adapter import Meko
from tests.conftest import MakeSettings
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
SALARY = "Mara's salary (take-home pay a month)"


@asynccontextmanager
async def _no_meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
    yield None


async def _read(
    migrated: AsyncEngine, make_settings: MakeSettings, through: datetime
) -> tuple[dict[str, Any], dict[str, Any], list[int]]:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo(), through=through)
        await conn.commit()
    settings = make_settings()
    async with httpx.AsyncClient() as http:
        services = Services(
            settings, migrated, _no_meko, lambda: ScriptedBackend({}), http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            timeline = await api.get("/api/v1/timeline")
            decisions = await api.get("/api/v1/decisions")
            elsewhere = [
                (await api.get(path, params={"household_id": str(uuid.uuid4())})).status_code
                for path in ("/api/v1/timeline", "/api/v1/decisions")
            ]
    assert timeline.status_code == 200, timeline.text
    assert decisions.status_code == 200, decisions.text
    return timeline.json(), decisions.json(), elsewhere


async def test_the_new_job_ahead_and_the_decisions_to_revisit(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    timeline, decided, elsewhere = await _read(
        migrated, make_settings, datetime(2026, 11, 20, 20, 30, tzinfo=MANILA)
    )
    assert elsewhere == [404, 404]
    assert timeline["as_of"] == "2026-11-20"

    # What happened, newest first: the new job is ahead, with the salary it replaces.
    events = timeline["events"]
    assert [e["on"] for e in events] == sorted((e["on"] for e in events), reverse=True)
    job = events[0]
    assert (job["kind"], job["on"], job["ahead"], job["detail"]) == (
        "life_event",
        "2026-12-01",
        True,
        "New job",
    )
    assert job["changes"] == [
        {
            "label": "replaced",
            "title": SALARY,
            "before": "₱52,000.00",
            "after": "₱68,000.00",
            "from_day": "Dec 1, 2026",
        }
    ]
    assert "approved by Mara on Nov 20, 2026" in job["source"]
    assert job["by"] == "Mara"  # who said yes, for the line under its headline
    assert all(not e["ahead"] for e in events[1:] if e["on"] <= "2026-11-20")
    statement = next(e for e in events if e["kind"] == "change" and e["on"] == "2026-11-15")
    assert statement["title"] == "New statements"
    assert statement["source"].startswith(f"From a statement, approved by {statement['by']} ")
    assert {c["title"] for c in statement["changes"]} == {
        "Car loan (balance)",
        "Credit card (balance)",
        "Emergency fund (balance)",
    }
    learned = next(e for e in events if e["title"] == "Learned by dreaming")
    assert learned["on"] == "2026-10-18"
    choices = [e for e in events if e["kind"] == "decision"]
    assert [(e["source"], e["revisit"], e["by"]) for e in choices] == [
        ("Decided by Jun in Session 3", True, "Jun"),
        ("Decided by Mara in Session 2", True, "Mara"),
        ("Decided by Jun in Session 1", True, "Jun"),
    ]
    assert events[-1]["kind"] == "start"
    assert events[-1]["by"] is None  # the starting figures: nobody approved them one by one
    assert events[-1]["on"] == "2026-08-01"

    # Each thing over time: her salary now, and the one coming.
    mara = next(t for t in timeline["things"] if t["name"] == "Mara's salary")
    pay = next(a for a in mara["attributes"] if a["attribute"] == "income.monthly_net")
    assert [(v["value"], v["valid_from"], v["valid_to"], v["state"]) for v in pay["values"]] == [
        ("₱68,000.00", "2026-12-01", None, "coming"),
        ("₱52,000.00", "2026-03-01", "2026-12-01", "current"),
    ]
    assert pay["values"][1]["source"] == "From the household's starting figures"
    household = timeline["things"][0]
    assert household["id"] is None
    flexible = next(
        a for a in household["attributes"] if a["attribute"] == "preference.debt_vs_flexibility"
    )
    assert flexible["values"][0]["value"] == "flexibility"
    assert flexible["values"][0]["source"].startswith("Learned by dreaming")

    # The decisions, newest first, each with what it didn't choose and why, and what moved.
    assert decided["as_of"] == "2026-11-20"
    found = decided["decisions"]
    assert [(d["session_title"], d["on"], d["chosen"]) for d in found] == [
        ("Session 3", "2026-10-18", "B: keep it for the trip"),
        ("Session 2", "2026-09-15", "B: split"),
        ("Session 1", "2026-08-15", "B: bigger buffer"),
    ]
    split = found[1]
    assert (split["decided_by"], split["said_by"], split["status"]) == ("Mara", "Mara", "active")
    assert split["reasoning"] == "Lia starts school and we want cash on hand."
    assert split["quote"] is not None
    assert "Lia starts school" in split["quote"]
    assert [(o["label"], o["chosen"], o["leans"]) for o in split["options"]] == [
        ("B: split", True, ["keeps cash on hand"]),
        ("A: all extra on the card", False, ["pays debt off faster"]),
    ]
    assert split["options"][0]["reason"] is None
    assert split["options"][1]["reason"]
    for d in found:
        assert d["revisit"] == [
            {
                "label": "replaced",
                "title": SALARY,
                "before": "₱52,000.00",
                "after": "₱68,000.00",
                "from_day": "Dec 1, 2026",
            }
        ]
        moved = [r for r in d["rests_on"] if r["moved"]]
        assert [r["title"] for r in moved] == [SALARY]
        # What each fact is about, so the screen can group them by thing.
        assert {k: moved[0][k] for k in ("thing", "kind", "words", "value")} == {
            "thing": "Mara's salary",
            "kind": "income",
            "words": "take-home pay a month",
            "value": "₱52,000.00",
        }
        rules = [r for r in d["rests_on"] if r["kind"] == "household"]
        assert rules
        assert all(r["thing"] == "The household" for r in rules)
        # Balances move as the plan works, so a decision doesn't rest on them.
        assert not any(r["title"].endswith("(balance)") for r in d["rests_on"])


async def test_nothing_to_revisit_before_the_new_job(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    timeline, decided, _ = await _read(
        migrated, make_settings, datetime(2026, 10, 20, 23, tzinfo=MANILA)
    )
    assert timeline["as_of"] == "2026-10-20"
    assert not any(e["kind"] == "life_event" for e in timeline["events"])
    assert not any(e["ahead"] for e in timeline["events"])
    assert [d["revisit"] for d in decided["decisions"]] == [[], [], []]
    assert not any(e["revisit"] for e in timeline["events"])
