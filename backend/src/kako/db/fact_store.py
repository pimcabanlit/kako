"""The fact store: record, replace and retract facts, and read snapshots, in Postgres.

Every write is one transaction that locks the household's row first, so two writes to the same
household can't interleave. The rules are checked here before writing, with plain-language errors;
the database guard (migration 0003) and the check constraints refuse the same things again, so no
other code path can break them.

docs/data-model.md, "Facts": a change is a new fact that replaces the old one; a mistake is
retracted, never deleted; every non-seed fact comes from an approved proposal (V-08).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, cast

from sqlalchemy import Table, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.models import Decision, Entity, Fact, Household, LifeEvent, Proposal
from kako.facts.attributes import Attribute, attribute
from kako.facts.model import EntityRow, FactRow, FactValue, SourceKind
from kako.facts.rules import ApprovedRow, Violation, validate, windows_overlap
from kako.facts.snapshot import Snapshot, take_snapshot
from kako.facts.values import FactValueError, value_columns

FACT = cast(Table, Fact.__table__)
ENTITY = cast(Table, Entity.__table__)
PROPOSAL = cast(Table, Proposal.__table__)

# Which approved proposals can create, replace or retract a fact.
RECORD_KINDS: Final = frozenset({"new_fact", "preference_pattern"})
REPLACE_KINDS: Final = frozenset({"replace_fact", "preference_pattern"})
RETRACT_KINDS: Final = frozenset({"retract_fact"})


class FactStoreError(Exception):
    """A write the rules refuse. The message says why in plain words."""


@dataclass(frozen=True)
class NewFact:
    """A value to record. `valid_to` is set only for a period already known to have ended."""

    household_id: uuid.UUID
    entity_id: uuid.UUID | None
    attribute: str
    value: FactValue
    valid_from: date
    source_kind: SourceKind
    source_ref: str
    valid_to: date | None = None
    life_event_id: uuid.UUID | None = None


@asynccontextmanager
async def _atomic(conn: AsyncConnection) -> AsyncIterator[None]:
    """One transaction: the caller's (as a savepoint) or a new one."""
    if conn.in_transaction():
        async with conn.begin_nested():
            yield
    else:
        async with conn.begin():
            yield


def _fact_row(mapping: Any) -> FactRow:
    return FactRow(**{name: mapping[name] for name in FactRow.__dataclass_fields__})


async def _lock_household(conn: AsyncConnection, household_id: uuid.UUID) -> None:
    found = await conn.execute(
        select(Household.__table__.c.id)
        .where(Household.__table__.c.id == household_id)
        .with_for_update()
    )
    if found.scalar_one_or_none() is None:
        raise FactStoreError(f"household {household_id} doesn't exist")


async def _get_fact(conn: AsyncConnection, fact_id: uuid.UUID) -> FactRow:
    row = (await conn.execute(select(FACT).where(FACT.c.id == fact_id))).mappings().one_or_none()
    if row is None:
        raise FactStoreError(f"fact {fact_id} doesn't exist")
    return _fact_row(row)


async def load_facts(conn: AsyncConnection, household_id: uuid.UUID) -> list[FactRow]:
    """Every fact of a household, in every status, in one query."""
    result = await conn.execute(
        select(FACT).where(FACT.c.household_id == household_id).order_by(FACT.c.id)
    )
    return [_fact_row(row) for row in result.mappings()]


async def load_entities(conn: AsyncConnection, household_id: uuid.UUID) -> list[EntityRow]:
    result = await conn.execute(
        select(
            ENTITY.c.id,
            ENTITY.c.household_id,
            ENTITY.c.kind,
            ENTITY.c.name,
            ENTITY.c.opened_on,
            ENTITY.c.closed_on,
        )
        .where(ENTITY.c.household_id == household_id)
        .order_by(ENTITY.c.id)
    )
    return [EntityRow(**row) for row in result.mappings()]


async def snapshot(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    on: date,
    known_at: datetime | None = None,
) -> Snapshot:
    """What was true on `on`, as Kako knew it at `known_at` (None: now). One query."""
    return take_snapshot(household_id, await load_facts(conn, household_id), on, known_at)


async def _check_proposal(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    proposal_id: uuid.UUID | None,
    kinds: frozenset[str],
) -> None:
    if proposal_id is None:
        raise FactStoreError("only the seed is recorded without an approved proposal (V-08)")
    row = (
        (
            await conn.execute(
                select(PROPOSAL.c.household_id, PROPOSAL.c.status, PROPOSAL.c.kind).where(
                    PROPOSAL.c.id == proposal_id
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["household_id"] != household_id:
        raise FactStoreError(f"proposal {proposal_id} isn't this household's")
    if row["status"] != "approved":
        raise FactStoreError(f"proposal {proposal_id} is {row['status']}, not approved (V-08)")
    if row["kind"] not in kinds:
        allowed = ", ".join(sorted(kinds))
        raise FactStoreError(f"a {row['kind']} proposal can't do this; it takes {allowed}")


async def _check_new(
    conn: AsyncConnection, new: NewFact, proposal_id: uuid.UUID | None, kinds: frozenset[str]
) -> tuple[Attribute, dict[str, FactValue | None]]:
    """The checks every new fact passes: catalog, value, entity, window and source."""
    try:
        attr = attribute(new.attribute)
        columns = value_columns(attr, new.value)
    except (KeyError, FactValueError) as exc:
        raise FactStoreError(str(exc).strip("'\"")) from exc
    if new.valid_to is not None and new.valid_to <= new.valid_from:
        raise FactStoreError("a fact's window must end after it starts")
    if attr.household_wide:
        if new.entity_id is not None:
            raise FactStoreError(f"{attr.key} is about the household, not an entity")
    else:
        if new.entity_id is None:
            raise FactStoreError(f"{attr.key} needs an entity")
        entity = (
            (await conn.execute(select(ENTITY).where(ENTITY.c.id == new.entity_id)))
            .mappings()
            .one_or_none()
        )
        if entity is None or entity["household_id"] != new.household_id:
            raise FactStoreError(f"entity {new.entity_id} isn't this household's")
        if entity["kind"] not in attr.entity_kinds:
            raise FactStoreError(
                f"{attr.key} doesn't describe {entity['name']}, which is a {entity['kind']} entity"
            )
        if entity["opened_on"] is not None and new.valid_from < entity["opened_on"]:
            raise FactStoreError(f"{entity['name']} opened on {entity['opened_on']} (V-06)")
        if entity["closed_on"] is not None and new.valid_from >= entity["closed_on"]:
            raise FactStoreError(f"{entity['name']} closed on {entity['closed_on']} (V-06)")
    if not new.source_ref.strip():
        raise FactStoreError("a fact needs a source reference")
    if new.source_kind == "seed":
        if proposal_id is not None:
            raise FactStoreError("a seed fact has no proposal")
    else:
        await _check_proposal(conn, new.household_id, proposal_id, kinds)
    return attr, columns


async def _check_one_emergency_fund(conn: AsyncConnection, new: NewFact) -> None:
    """V-16: at most one account is the emergency fund on any date."""
    if new.attribute != "account.purpose" or new.value != "emergency":
        return
    for fact in await load_facts(conn, new.household_id):
        if (
            fact.attribute == "account.purpose"
            and fact.value_text == "emergency"
            and fact.status in ("active", "replaced")
            and fact.entity_id != new.entity_id
            and windows_overlap(fact.valid_from, fact.valid_to, new.valid_from, new.valid_to)
        ):
            raise FactStoreError("another account is already the emergency fund then (V-16)")


def _row_values(
    new: NewFact,
    columns: dict[str, FactValue | None],
    *,
    proposal_id: uuid.UUID | None,
    recorded_at: datetime,
    replaces: uuid.UUID | None,
) -> dict[str, Any]:
    if recorded_at.tzinfo is None:
        raise FactStoreError("recorded_at must carry its time zone (UTC)")
    return {
        "id": uuid.uuid4(),
        "household_id": new.household_id,
        "entity_id": new.entity_id,
        "attribute": new.attribute,
        **columns,
        "valid_from": new.valid_from,
        "valid_to": new.valid_to,
        "replaces": replaces,
        "replaced_by": None,
        "status": "active",
        "recorded_at": recorded_at,
        "retracted_at": None,
        "retraction_reason": None,
        "source_kind": new.source_kind,
        "source_ref": new.source_ref,
        "proposal_id": proposal_id,
        "life_event_id": new.life_event_id,
    }


async def record_fact(
    conn: AsyncConnection,
    new: NewFact,
    *,
    proposal_id: uuid.UUID | None,
    recorded_at: datetime,
) -> FactRow:
    """Record a value for an entity and attribute that has no value in that window yet."""
    async with _atomic(conn):
        await _lock_household(conn, new.household_id)
        _, columns = await _check_new(conn, new, proposal_id, RECORD_KINDS)
        for fact in await load_facts(conn, new.household_id):
            if (
                fact.entity_id == new.entity_id
                and fact.attribute == new.attribute
                and fact.status in ("active", "replaced")
                and windows_overlap(fact.valid_from, fact.valid_to, new.valid_from, new.valid_to)
            ):
                raise FactStoreError(
                    f"{new.attribute} already has a value from {fact.valid_from}; "
                    "replace it instead (V-02)"
                )
        await _check_one_emergency_fund(conn, new)
        values = _row_values(
            new, columns, proposal_id=proposal_id, recorded_at=recorded_at, replaces=None
        )
        await conn.execute(FACT.insert().values(values))
        return await _get_fact(conn, values["id"])


async def replace_fact(
    conn: AsyncConnection,
    old_id: uuid.UUID,
    new: NewFact,
    *,
    proposal_id: uuid.UUID | None,
    recorded_at: datetime,
) -> FactRow:
    """A change in the household's life: the new value starts, and the old one ends that day.

    The old fact must be open (`active`, no end). The new one is inserted first, then the old one
    is closed (`valid_to` = the new start, `replaced_by` = the new fact, `replaced`), in one
    transaction.
    """
    async with _atomic(conn):
        await _lock_household(conn, new.household_id)
        old = await _get_fact(conn, old_id)
        if old.household_id != new.household_id:
            raise FactStoreError(f"fact {old_id} isn't this household's")
        if (old.entity_id, old.attribute) != (new.entity_id, new.attribute):
            raise FactStoreError("a replacement is for the same entity and attribute")
        if old.status != "active" or old.valid_to is not None:
            raise FactStoreError(
                f"fact {old_id} is {old.status}"
                + (f" and ended {old.valid_to}" if old.valid_to else "")
                + "; only an open, active fact can be replaced"
            )
        if new.valid_from <= old.valid_from:
            raise FactStoreError(
                f"the new value must start after {old.valid_from}, when the old one started"
            )
        if new.valid_to is not None:
            raise FactStoreError("a replacement starts open; it ends when it is replaced")
        if recorded_at < old.recorded_at:
            raise FactStoreError("a replacement can't be recorded before the fact it replaces")
        _, columns = await _check_new(conn, new, proposal_id, REPLACE_KINDS)
        await _check_one_emergency_fund(conn, new)
        values = _row_values(
            new, columns, proposal_id=proposal_id, recorded_at=recorded_at, replaces=old.id
        )
        await conn.execute(FACT.insert().values(values))
        await conn.execute(
            update(FACT)
            .where(FACT.c.id == old.id)
            .values(valid_to=new.valid_from, replaced_by=values["id"], status="replaced")
        )
        return await _get_fact(conn, values["id"])


async def retract_fact(
    conn: AsyncConnection,
    fact_id: uuid.UUID,
    *,
    reason: str,
    proposal_id: uuid.UUID,
    retracted_at: datetime,
) -> FactRow:
    """A mistake: the fact was never true. It stays, marked retracted with the reason.

    Only an `active` fact can be retracted; a fact already replaced keeps its place in the
    history (retract its replacement first). If the fact had replaced an earlier one, that one is
    opened again in the same transaction: it was true all along.
    """
    if not reason.strip():
        raise FactStoreError("a retraction needs a reason")
    if retracted_at.tzinfo is None:
        raise FactStoreError("retracted_at must carry its time zone (UTC)")
    async with _atomic(conn):
        fact = await _get_fact(conn, fact_id)
        await _lock_household(conn, fact.household_id)
        fact = await _get_fact(conn, fact_id)  # read again under the lock
        if fact.status != "active":
            hint = "; retract its replacement first" if fact.status == "replaced" else ""
            raise FactStoreError(f"fact {fact_id} is {fact.status}{hint}")
        if retracted_at < fact.recorded_at:
            raise FactStoreError("a fact can't be retracted before it was recorded")
        await _check_proposal(conn, fact.household_id, proposal_id, RETRACT_KINDS)
        await conn.execute(
            update(FACT)
            .where(FACT.c.id == fact.id)
            .values(status="retracted", retracted_at=retracted_at, retraction_reason=reason)
        )
        if fact.replaces is not None:
            reopened = await conn.execute(
                update(FACT)
                .where(FACT.c.id == fact.replaces, FACT.c.replaced_by == fact.id)
                .values(status="active", valid_to=None, replaced_by=None)
            )
            if reopened.rowcount != 1:
                raise FactStoreError(
                    f"fact {fact.replaces}, which {fact_id} replaced, doesn't name it back (V-04)"
                )
        return await _get_fact(conn, fact.id)


async def validate_household(conn: AsyncConnection, household_id: uuid.UUID) -> list[Violation]:
    """Rules V-01 to V-08 and V-16 over everything stored for one household."""
    approved = await conn.execute(
        select(PROPOSAL.c.id).where(
            PROPOSAL.c.household_id == household_id, PROPOSAL.c.status == "approved"
        )
    )
    rows: list[ApprovedRow] = []
    for model, table in ((Decision, "decision"), (LifeEvent, "life_event")):
        t = model.__table__
        result = await conn.execute(
            select(t.c.id, t.c.proposal_id).where(t.c.household_id == household_id)
        )
        rows += [ApprovedRow(table, r.id, r.proposal_id) for r in result]
    return validate(
        await load_facts(conn, household_id),
        await load_entities(conn, household_id),
        set(approved.scalars()),
        rows,
    )
