"""The approvals API: what waits for the household, and their yes or no.

- `GET /api/v1/proposals` lists the household's proposals (pending by default), each with what it
  would write in plain words, its evidence (the quote and who said it), who decided and when, and
  what an approved one wrote. Approved preferences listed here, with their source and date, are
  what a "What Kako knows about you" view reads.
- `POST /api/v1/proposals/approve` approves one or more proposals in one transaction and writes
  what each names (`db.proposal_store.approve`). Approving an approved proposal again changes
  nothing and says so (`already`). After the answer, Meko upkeep brings Meko in line with what
  was written (`kako.upkeep`): a failure there never undoes the approval.
- `POST /api/v1/proposals/reject` rejects pending proposals; nothing is written.

Kako has no sign-in yet, so the person deciding is named in the request, and must be an adult of
the household. The app answers only on loopback (see `api.app`), and these routes take JSON only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.agents.present import day, fact_value, money
from kako.api.sessions import Services, _household, _services
from kako.db.fact_store import load_entities, load_facts
from kako.db.models import Person
from kako.db.proposal_store import (
    MAX_BATCH,
    Decided,
    ProposalError,
    ProposalView,
    approve,
    list_proposals,
    reject,
)
from kako.facts.attributes import attribute
from kako.facts.model import EntityRow, FactRow
from kako.facts.proposals import FACT_KINDS, PayloadError, decode_value, parse_fact
from kako.health import safe_error

PERSON = cast(Table, Person.__table__)
log = logging.getLogger(__name__)
JSON_ONLY = "application/json"

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Decide(_In):
    proposal_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=MAX_BATCH)]
    person_id: uuid.UUID  # the adult who decides (no sign-in yet)
    household_id: uuid.UUID | None = None  # unset: the only household


class EvidenceOut(BaseModel):
    kind: str
    ref: str
    quote: str
    said_by: str | None


class WrittenOut(BaseModel):
    table: str
    id: uuid.UUID


class ProposalOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    shown: str  # what it would write, in plain words
    explanation: str
    payload: dict[str, object]
    from_dreaming: bool
    created_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    evidence: list[EvidenceOut]
    written: list[WrittenOut]


class DecidedOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    already: bool  # it was already decided this way: nothing changed
    written: list[WrittenOut]


def _value(attribute_key: str, raw: object) -> str:
    """A payload's value in words, the way facts are shown."""
    attr = attribute(attribute_key)
    try:
        value = decode_value(attr, raw)
    except ValueError:
        return str(raw)
    if attr.value_type == "money" and isinstance(value, int):
        return money(value)
    if isinstance(value, Decimal):
        period = "a month" if attribute_key.endswith("monthly_rate") else "a year"
        return f"{(value * 100).normalize():f}% {period}"
    if isinstance(value, date):
        return day(value)
    return str(value)


def describe(view: ProposalView, entities: Sequence[EntityRow], facts: Sequence[FactRow]) -> str:
    """What a proposal would write, in plain words, from its payload and the household's rows."""
    names = {e.id: e.name for e in entities}
    by_id = {f.id: f for f in facts}
    payload = view.payload
    try:
        if view.kind in FACT_KINDS:
            write = parse_fact(view.kind, payload)
            whose = names.get(write.entity_id, "The household") if write.entity_id else "Household"
            text = (
                f"{whose}: {write.attribute} = {_value(write.attribute, payload['value'])} "
                f"from {day(write.valid_from)}"
            )
            old = by_id.get(write.replaces) if write.replaces else None
            if old is not None:
                text += f", replacing {fact_value(old)} (since {day(old.valid_from)})"
            return text
        if view.kind == "retract_fact":
            fact = by_id.get(uuid.UUID(str(payload["fact_id"])))
            what = (
                f"{names.get(fact.entity_id, 'Household') if fact.entity_id else 'Household'}: "
                f"{fact.attribute} = {fact_value(fact)}"
                if fact
                else "a fact"
            )
            return f"Retract {what}, because: {payload['reason']}"
        if view.kind == "life_event":
            occurs_on = date.fromisoformat(str(payload["occurs_on"]))
            return f"Life event ({payload['kind']}) on {day(occurs_on)}: {payload['description']}"
        if view.kind == "decision":
            return f"Decision: {payload['question']} Chosen: {payload['chosen']}"
    except (KeyError, ValueError, PayloadError):
        pass  # shown as its kind below; the payload itself is in the response
    return view.kind.replace("_", " ")


def _written(decided: Decided | ProposalView) -> list[WrittenOut]:
    return [WrittenOut(table=w.table, id=w.row_id) for w in decided.written]


def _json_only(request: Request) -> None:
    """Refuse a body that isn't JSON, so a page on another site can't post a form to the
    loopback API (a JSON request from another origin needs CORS, which the app doesn't allow)."""
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind != JSON_ONLY:
        raise HTTPException(415, "send the request as application/json")


async def _views(
    conn: AsyncConnection, household_id: uuid.UUID, views: list[ProposalView]
) -> list[ProposalOut]:
    entities = await load_entities(conn, household_id)
    facts = await load_facts(conn, household_id)
    return [
        ProposalOut(
            id=v.id,
            kind=v.kind,
            status=v.status,
            shown=describe(v, entities, facts),
            explanation=v.explanation,
            payload=v.payload,
            from_dreaming=v.from_dreaming,
            created_at=v.created_at,
            decided_by=v.decided_by,
            decided_at=v.decided_at,
            evidence=[EvidenceOut(**e.__dict__) for e in v.evidence],
            written=_written(v),
        )
        for v in views
    ]


@router.get("", response_model=list[ProposalOut])
async def read_proposals(
    request: Request,
    status: Annotated[
        Literal["pending", "approved", "rejected", "expired", "all"], Query()
    ] = "pending",
    household_id: uuid.UUID | None = None,
) -> list[ProposalOut]:
    """The household's proposals, newest first: pending ones by default."""
    services: Services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        views = await list_proposals(conn, household, status=None if status == "all" else status)
        return await _views(conn, household, views)


async def _upkeep(services: Services, household_id: uuid.UUID) -> None:
    """After an approval: Meko upkeep for the household (`kako.upkeep`). It never undoes or
    fails the approval: what it can't do now, `kako meko sync` does later."""
    from kako.db.meko_log import DbCallLog
    from kako.meko.client import MekoError
    from kako.upkeep.sync import MAX_STEPS, UpkeepError, keep_up

    try:
        async with services.open_meko(DbCallLog(services.engine), 1 + MAX_STEPS) as meko:
            if meko is not None:
                await keep_up(services.engine, meko, household_id, now=datetime.now(UTC))
    except (MekoError, UpkeepError) as exc:
        log.warning("Meko upkeep after an approval didn't run: %s", safe_error(exc))


async def _decide(
    request: Request,
    body: Decide,
    action: Literal["approve", "reject"],
    tasks: BackgroundTasks | None = None,
) -> list[DecidedOut]:
    _json_only(request)
    services: Services = _services(request)
    household, _ = await _household(services.engine, body.household_id)
    decide = approve if action == "approve" else reject
    async with services.engine.begin() as conn:
        mine = await list_proposals(
            conn, household, proposal_ids=body.proposal_ids, limit=MAX_BATCH
        )
        if len(mine) != len(set(body.proposal_ids)):
            raise HTTPException(404, "no such proposal in this household")
        try:
            decided = await decide(
                conn, body.proposal_ids, person_id=body.person_id, decided_at=datetime.now(UTC)
            )
        except ProposalError as exc:
            raise HTTPException(409, str(exc)) from None
    if tasks is not None and any(not d.already for d in decided):
        tasks.add_task(_upkeep, services, household)
    return [
        DecidedOut(
            id=d.proposal_id, kind=d.kind, status=d.status, already=d.already, written=_written(d)
        )
        for d in decided
    ]


@router.post("/approve", response_model=list[DecidedOut])
async def approve_proposals(
    body: Decide, request: Request, tasks: BackgroundTasks
) -> list[DecidedOut]:
    """Approve the proposals together and write what each names. If any write is refused, none
    is made (409, with the reason). Then, after the answer, Meko upkeep for the household."""
    return await _decide(request, body, "approve", tasks)


@router.post("/reject", response_model=list[DecidedOut])
async def reject_proposals(body: Decide, request: Request) -> list[DecidedOut]:
    """Reject pending proposals. Nothing is written."""
    return await _decide(request, body, "reject")


async def people(conn: AsyncConnection, household_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """The household's people by display name, for the command line."""
    rows = await conn.execute(
        select(PERSON.c.display_name, PERSON.c.id).where(PERSON.c.household_id == household_id)
    )
    return {name.lower(): person_id for name, person_id in rows}
