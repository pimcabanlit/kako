"""Load the demo household into Postgres, through the same fact store a real household uses.

The seed goes in as seed facts. Each later change becomes a proposal an adult approved, and then the
write that proposal names, so V-08 holds for every fact after the seed (Pim, Nov 17). `through`
stops the replay at a point in the story; without it, only the seed is loaded.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, time
from typing import Any, cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.fact_store import (
    NewFact,
    load_facts,
    record_fact,
    record_seed_fact,
    replace_fact,
)
from kako.db.models import Entity, Household, LifeEvent, Person, Proposal
from kako.demo.files import Change, DemoHousehold
from kako.facts.proposals import fact_payload

HOUSEHOLD = cast(Table, Household.__table__)
PERSON = cast(Table, Person.__table__)
ENTITY = cast(Table, Entity.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)


class DemoLoadError(Exception):
    """The demo can't be loaded here, such as into a database that already holds it."""


def seed_time(demo: DemoHousehold) -> datetime:
    """When the seed is recorded: the start of the household's first day, in UTC."""
    return datetime.combine(demo.household.as_of_date, time(), tzinfo=UTC)


async def load_demo(
    conn: AsyncConnection, demo: DemoHousehold, *, through: datetime | None = None
) -> uuid.UUID:
    """Load the household, its seed, and every change recorded up to `through`. One transaction."""
    if through is not None and through.tzinfo is None:
        raise DemoLoadError("--through needs its time zone, such as 2026-12-01T12:00+08:00")
    async with conn.begin_nested() if conn.in_transaction() else conn.begin():
        existing = await conn.execute(
            select(HOUSEHOLD.c.id).where(HOUSEHOLD.c.name == demo.household.name)
        )
        if existing.first() is not None:
            raise DemoLoadError(f"{demo.household.name} is already loaded")
        h = demo.household
        household_id = uuid.uuid4()
        as_of = through.date() if through is not None else h.as_of_date
        await conn.execute(
            HOUSEHOLD.insert().values(
                id=household_id,
                name=h.name,
                currency=h.currency,
                timezone=h.timezone,
                as_of_date=max(as_of, h.as_of_date),
                created_at=seed_time(demo),
            )
        )
        people: dict[str, uuid.UUID] = {}
        for person in demo.people:
            people[person.key] = uuid.uuid4()
            await conn.execute(
                PERSON.insert().values(
                    id=people[person.key],
                    household_id=household_id,
                    display_name=person.display_name,
                    role=person.role,
                    birth_year=person.birth_year,
                )
            )
        entities: dict[str, uuid.UUID] = {}
        for entity in demo.entities:
            entities[entity.key] = uuid.uuid4()
            await conn.execute(
                ENTITY.insert().values(
                    id=entities[entity.key],
                    household_id=household_id,
                    kind=entity.kind,
                    name=entity.name,
                    owner_person_id=people[entity.owner] if entity.owner else None,
                    opened_on=entity.opened_on,
                    closed_on=entity.closed_on,
                )
            )
        for seed in demo.facts:
            await record_seed_fact(
                conn,
                NewFact(
                    household_id=household_id,
                    entity_id=entities[seed.entity] if seed.entity else None,
                    attribute=seed.attribute,
                    value=seed.value,
                    valid_from=seed.valid_from,
                    source_kind="seed",
                    source_ref=seed.source_ref,
                ),
                recorded_at=seed_time(demo),
            )
        events: dict[str, uuid.UUID] = {}
        for change in demo.changes if through is not None else ():
            if change.recorded_at > through:  # type: ignore[operator]
                break
            await _apply(conn, household_id, change, people, entities, events)
        return household_id


async def _proposal(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    change: Change,
    kind: str,
    payload: dict[str, Any],
    decided_by: uuid.UUID,
) -> uuid.UUID:
    proposal_id = uuid.uuid4()
    await conn.execute(
        PROPOSAL.insert().values(
            id=proposal_id,
            household_id=household_id,
            kind=kind,
            payload=payload,
            explanation=change.explanation,
            status="approved",
            decided_by_person_id=decided_by,
            decided_at=change.recorded_at,
            idempotency_key=f"demo:{household_id}:{change.seq}",
            created_at=change.recorded_at,
        )
    )
    return proposal_id


async def _apply(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    change: Change,
    people: Mapping[str, uuid.UUID],
    entities: Mapping[str, uuid.UUID],
    events: dict[str, uuid.UUID],
) -> None:
    decided_by = people[change.decided_by]
    if change.kind == "life_event":
        if change.life_event is None:
            raise DemoLoadError(f"life event {change.seq} has no key")
        payload = {
            "kind": change.attribute,
            "description": change.value,
            "occurs_on": change.valid_from.isoformat(),
        }
        proposal_id = await _proposal(conn, household_id, change, "life_event", payload, decided_by)
        events[change.life_event] = uuid.uuid4()
        await conn.execute(
            LIFE_EVENT.insert().values(
                id=events[change.life_event],
                household_id=household_id,
                kind=change.attribute,
                description=str(change.value),
                occurs_on=change.valid_from,
                recorded_at=change.recorded_at,
                source_ref=change.source_ref,
                proposal_id=proposal_id,
            )
        )
        return
    new = NewFact(
        household_id=household_id,
        entity_id=entities[change.entity] if change.entity else None,
        attribute=change.attribute,
        value=change.value,
        valid_from=change.valid_from,
        source_kind=change.source_kind,
        source_ref=change.source_ref,
        life_event_id=events[change.life_event] if change.life_event else None,
    )
    current = [
        f
        for f in await load_facts(conn, household_id)
        if (f.entity_id, f.attribute) == (new.entity_id, new.attribute)
        and f.status == "active"
        and f.valid_to is None
    ]
    replaces = current[0].id if current and change.kind != "new_fact" else None
    if change.kind == "replace_fact" and replaces is None:
        raise DemoLoadError(f"change {change.seq} replaces a fact that isn't there")
    payload = fact_payload(
        entity_id=new.entity_id,
        attribute_key=new.attribute,
        value=new.value,
        valid_from=new.valid_from,
        replaces=replaces,
        life_event_id=new.life_event_id,
    )
    proposal_id = await _proposal(conn, household_id, change, change.kind, payload, decided_by)
    if replaces is None:
        await record_fact(conn, new, proposal_id=proposal_id, recorded_at=change.recorded_at)
    else:
        await replace_fact(
            conn, replaces, new, proposal_id=proposal_id, recorded_at=change.recorded_at
        )
