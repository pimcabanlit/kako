"""The household API: who the household is, for the screens.

- `GET /api/v1/household` is the household (the only one, or `household_id`) with its people: the
  session screen's "writing as" picker, and who may approve (an adult).

Read-only. Kako has no sign-in yet: the app answers only on loopback (see `api.app`).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import Table, case, select

from kako.api.sessions import _household, _services
from kako.db.models import Household, Person

HOUSEHOLD = cast(Table, Household.__table__)
PERSON = cast(Table, Person.__table__)

router = APIRouter(prefix="/api/v1/household", tags=["household"])


class PersonOut(BaseModel):
    id: uuid.UUID
    display_name: str
    role: str  # adult or child: only an adult approves


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str
    currency: str
    as_of_date: date
    people: list[PersonOut]


@router.get("", response_model=HouseholdOut)
async def read_household(request: Request, household_id: uuid.UUID | None = None) -> HouseholdOut:
    """The household and its people, adults first."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        row = (
            await conn.execute(
                select(HOUSEHOLD.c.name, HOUSEHOLD.c.currency, HOUSEHOLD.c.as_of_date).where(
                    HOUSEHOLD.c.id == household
                )
            )
        ).one()
        people = await conn.execute(
            select(PERSON.c.id, PERSON.c.display_name, PERSON.c.role)
            .where(PERSON.c.household_id == household)
            .order_by(case((PERSON.c.role == "adult", 0), else_=1), PERSON.c.display_name)
        )
        return HouseholdOut(
            id=household,
            name=row.name,
            currency=row.currency,
            as_of_date=row.as_of_date,
            people=[PersonOut(id=p.id, display_name=p.display_name, role=p.role) for p in people],
        )
