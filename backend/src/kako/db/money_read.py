"""What the money screen reads: the household's facts as known now, on its date, and its decisions
in force. Reads only, and only the household's rows; `planning.money` works out the rest.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.fact_store import load_entities, load_facts
from kako.db.history_read import read_decisions
from kako.db.models import Household
from kako.planning.money import DecisionLine, MoneyScreen, money_screen

HOUSEHOLD = cast(Table, Household.__table__)


async def read_money(conn: AsyncConnection, household_id: uuid.UUID) -> MoneyScreen:
    """The money screen for the household on its date, with its decisions in force."""
    on = (
        await conn.execute(select(HOUSEHOLD.c.as_of_date).where(HOUSEHOLD.c.id == household_id))
    ).scalar_one()
    facts = await load_facts(conn, household_id)
    entities = await load_entities(conn, household_id)
    screen = money_screen(facts, entities, household_id, on)
    decided = await read_decisions(conn, household_id)
    in_force = tuple(
        DecisionLine(d.id, d.question, d.chosen, d.on, d.session_title, len(d.revisit))
        for d in decided.decisions
        if d.status == "active"
    )
    return replace(screen, decisions=in_force)
