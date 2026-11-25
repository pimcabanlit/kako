"""What the money screen reads (Phase 5a, item 4), on the demo household loaded through Dec 1.

Mara's new job counts from Dec 1 and plan v3 is in force: ₱116,000.00 a month, all of the
₱25,050.00 free after expenses planned, the card gone Jul 1, 2027 with its ₱12,550.00 rolling to the
car loan from Aug 1, 2027, and the plan before Dec 1 beside it. Every number is the engine's.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import Services
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from tests.conftest import MakeSettings
from tests.integration.test_history_api import _no_meko
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))


async def test_the_money_screen_on_dec_1(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo(), through=datetime(2026, 12, 1, 12, tzinfo=MANILA))
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
            response = await api.get("/api/v1/money")
            elsewhere = await api.get("/api/v1/money", params={"household_id": str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    assert elsewhere.status_code == 404
    money = response.json()

    assert money["as_of"] == "2026-12-01"
    assert [(t["label"], t["value"]) for t in money["tiles"]] == [
        ("Total salary", "₱116,000.00"),
        ("Free after expenses", "₱25,050.00"),
        ("Emergency cover", "2.3 months"),
        ("Net worth", "-₱288,210.63"),
    ]
    assert [(p["key"], p["text"], p["share"]) for p in money["split"]["parts"]] == [
        ("needs", "₱70,000.00", "60%"),
        ("wants", "₱6,000.00", "5%"),
        ("debt", "₱24,950.00", "22%"),
        ("savings", "₱15,050.00", "13%"),
    ]

    plan, before = money["plan"], money["before"]
    assert plan["label"] == "From Dec 1, 2026"
    assert plan["unplanned"] == "₱0.00"
    assert {line["name"]: line["change"] for line in plan["lines"] if line["change"]} == {
        "Mara's salary": "was ₱52,000.00",
        "Credit card, extra": "was ₱4,000.00",
        "Emergency fund": "was ₱5,050.00",
        "House fund": "new",
    }
    assert before["label"] == "Before Dec 1, 2026"
    assert before["lines"][1]["left"] == "₱100,000.00"

    card, car = money["debts"]
    assert (card["name"], card["balance"], card["since"], card["payoff_on"]) == (
        "Credit card", "₱76,880.00", "2026-11-15", "2027-07-01",
    )  # fmt: skip
    assert len(card["rows"]) == 7
    assert card["interest_total"] == card["interest_left"] == "₱9,358.80"
    assert (car["name"], car["payoff_in"], len(car["rows"])) == ("Car loan", "22 months", 22)
    assert [(r["on"], r["rolled_in"], r["payment"]) for r in car["rows"] if r["rolled_in"]] == [
        ("2027-08-01", "₱12,550.00", "₱24,950.00")
    ]

    standing = money["standing"]
    assert (standing["owned"], standing["owed"], standing["net"]) == (
        "₱190,100.00", "₱478,310.63", "-₱288,210.63",
    )  # fmt: skip
    assert [m["name"] for m in money["milestones"]] == [
        "Emergency fund", "Credit card", "Car loan", "House fund",
    ]  # fmt: skip
    assert [m["title"] for m in money["moments"]] == ["Jun's salary (13th-month pay)"]
    # The three decisions of Sessions 1 to 3 are in force, each resting on Mara's old salary.
    assert [(d["session_title"], d["revisit"]) for d in money["decisions"]] == [
        ("Session 3", 1), ("Session 2", 1), ("Session 1", 1),
    ]  # fmt: skip
