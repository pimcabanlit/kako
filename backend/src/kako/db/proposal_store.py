"""Proposals and approvals: what an agent, dreaming or the household proposes, and the person who
says yes or no (docs/data-model.md, `proposal`; docs/architecture.md, "A person decides").

- `propose` stores a **pending** proposal with its evidence. Its payload is checked for its kind,
  every row it names must be this household's, and every number it would write must appear in its
  quotes (V-09). The idempotency key makes it once only: proposing the same thing from the same
  turn again returns the first proposal, and proposing something different under the same key is
  refused.
- `approve` writes what each proposal names, exactly and once (V-08), in one transaction: the fact
  through the fact store, the life event, or the decision with its options and assumptions.
  Approving a proposal that is already approved changes nothing and returns what it wrote.
- `reject` closes a pending proposal without writing anything.

Only an adult of the household decides. Nothing here calls a model or Meko.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, Literal, cast

from sqlalchemy import Table, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.fact_store import FactStoreError, NewFact, record_fact, replace_fact, retract_fact
from kako.db.models import (
    CalcRun,
    Decision,
    DecisionAssumption,
    DecisionOption,
    Entity,
    Fact,
    Household,
    LifeEvent,
    Person,
    Plan,
    Proposal,
    ProposalEvidence,
    Session,
)
from kako.decisions.tags import DECISION_TAGS
from kako.facts.evidence import unquoted
from kako.facts.model import SourceKind
from kako.facts.proposals import (
    FACT_KINDS,
    KINDS,
    MAX_TEXT,
    DecisionWrite,
    PayloadError,
    canonical_payload,
    parse_decision,
    parse_fact,
    parse_life_event,
    parse_retract,
)

PROPOSAL = cast(Table, Proposal.__table__)
EVIDENCE = cast(Table, ProposalEvidence.__table__)
PERSON = cast(Table, Person.__table__)
HOUSEHOLD = cast(Table, Household.__table__)
ENTITY = cast(Table, Entity.__table__)
FACT = cast(Table, Fact.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
ASSUMPTION = cast(Table, DecisionAssumption.__table__)
SESSION = cast(Table, Session.__table__)
PLAN = cast(Table, Plan.__table__)
CALC_RUN = cast(Table, CalcRun.__table__)

EVIDENCE_KINDS: Final = ("turn", "memory", "extracted_memory", "learning", "fact", "decision")
# Meko's own words: shown with a proposal, never a quote that holds one of its numbers (V-09).
NOT_QUOTED: Final = frozenset({"extracted_memory", "learning"})
MAX_QUOTE: Final = 4_000
MAX_EVIDENCE: Final = 10
MAX_BATCH: Final = 20
# The order a batch is written in: a life event before the facts that name it, a retraction before
# a fact that takes its place, the facts before the decision that rests on them.
PHASE: Final = {
    "life_event": 0,
    "retract_fact": 1,
    "new_fact": 2,
    "replace_fact": 2,
    "preference_pattern": 2,
    "decision": 3,
    "promote": 4,
}

Status = Literal["pending", "approved", "rejected", "expired"]


class ProposalError(Exception):
    """A proposal or a decision on one that the rules refuse. The message says why."""


class ProposalConflict(ProposalError):
    """Something else was already proposed under the same idempotency key."""


@dataclass(frozen=True)
class Evidence:
    kind: str  # turn, memory, extracted_memory, learning, fact, decision
    ref: str  # a turn's `<conversation id>:<seed>`, a memory id, or a Kako id
    quote: str  # the words the proposal rests on
    person_id: uuid.UUID | None = None  # who said it, for a turn


@dataclass(frozen=True)
class Proposed:
    proposal_id: uuid.UUID
    created: bool  # False: the same proposal was already there under its key


@dataclass(frozen=True)
class Written:
    table: str  # fact, life_event, decision
    row_id: uuid.UUID


@dataclass(frozen=True)
class Decided:
    proposal_id: uuid.UUID
    kind: str
    status: Status
    already: bool  # it was already decided this way: nothing changed
    written: tuple[Written, ...] = ()


@asynccontextmanager
async def _atomic(conn: AsyncConnection) -> AsyncIterator[None]:
    if conn.in_transaction():
        async with conn.begin_nested():
            yield
    else:
        async with conn.begin():
            yield


# --- Proposing ------------------------------------------------------------------------------


def _check_payload(kind: str, payload: Any) -> None:
    """The payload is the shape its kind writes."""
    if kind in FACT_KINDS:
        parse_fact(kind, payload)
    elif kind == "retract_fact":
        parse_retract(payload)
    elif kind == "life_event":
        parse_life_event(payload)
    elif kind == "decision":
        parse_decision(payload, DECISION_TAGS)
    elif kind == "promote":
        raise PayloadError("promotion comes with its second confirmation (Phase 4, task 4)")
    else:
        raise PayloadError(f"{kind!r} isn't a kind of proposal")


async def _one(conn: AsyncConnection, query: Any) -> Any:
    return (await conn.execute(query)).mappings().one_or_none()


async def _check_rows(
    conn: AsyncConnection, household_id: uuid.UUID, kind: str, payload: Any
) -> None:
    """Every row the payload names is this household's (and still there to act on)."""

    async def entity(entity_id: uuid.UUID) -> None:
        row = await _one(conn, select(ENTITY.c.household_id).where(ENTITY.c.id == entity_id))
        if row is None or row["household_id"] != household_id:
            raise ProposalError(f"entity {entity_id} isn't this household's")

    async def fact(fact_id: uuid.UUID) -> Any:
        row = await _one(conn, select(FACT).where(FACT.c.id == fact_id))
        if row is None or row["household_id"] != household_id:
            raise ProposalError(f"fact {fact_id} isn't this household's")
        return row

    if kind in FACT_KINDS:
        write = parse_fact(kind, payload)
        if write.entity_id is not None:
            await entity(write.entity_id)
        if write.replaces is not None:
            old = await fact(write.replaces)
            if old["status"] != "active" or old["valid_to"] is not None:
                raise ProposalError(f"fact {write.replaces} is no longer open to replace")
        if write.life_event_id is not None:
            await _check_life_event_named(conn, household_id, write.life_event_id)
    elif kind == "retract_fact":
        fact_id, _ = parse_retract(payload)
        if (await fact(fact_id))["status"] != "active":
            raise ProposalError(f"fact {fact_id} isn't active, so it can't be retracted")
    elif kind == "decision":
        await _check_decision_rows(conn, household_id, parse_decision(payload, DECISION_TAGS))


async def _check_life_event_named(
    conn: AsyncConnection, household_id: uuid.UUID, event_id: uuid.UUID
) -> None:
    """A fact may name a life event that exists, or one proposed (pending or approved) with that
    id: the two are approved together, the event first."""
    row = await _one(conn, select(LIFE_EVENT.c.household_id).where(LIFE_EVENT.c.id == event_id))
    if row is not None:
        if row["household_id"] != household_id:
            raise ProposalError(f"life event {event_id} isn't this household's")
        return
    proposed = await _one(
        conn,
        select(PROPOSAL.c.id).where(
            PROPOSAL.c.household_id == household_id,
            PROPOSAL.c.kind == "life_event",
            PROPOSAL.c.status.in_(("pending", "approved")),
            PROPOSAL.c.payload["id"].astext == str(event_id),
        ),
    )
    if proposed is None:
        raise ProposalError(f"life event {event_id} hasn't been proposed")


async def _check_decision_rows(
    conn: AsyncConnection, household_id: uuid.UUID, write: DecisionWrite
) -> None:
    session = await _one(
        conn, select(SESSION.c.household_id).where(SESSION.c.id == write.session_id)
    )
    if session is None or session["household_id"] != household_id:
        raise ProposalError(f"session {write.session_id} isn't this household's")
    if write.plan_id is not None:
        plan = await _one(
            conn, select(PLAN.c.household_id, PLAN.c.status).where(PLAN.c.id == write.plan_id)
        )
        if plan is None or plan["household_id"] != household_id:
            raise ProposalError(f"plan {write.plan_id} isn't this household's")
        if plan["status"] != "proposed":
            raise ProposalError(f"plan {write.plan_id} is {plan['status']}, not proposed")
    runs = {o.calc_run_id for o in write.options if o.calc_run_id is not None}
    if runs:
        found = await conn.execute(
            select(CALC_RUN.c.id).where(
                CALC_RUN.c.id.in_(list(runs)), CALC_RUN.c.household_id == household_id
            )
        )
        missing = runs - set(found.scalars())
        if missing:
            raise ProposalError(f"run {sorted(map(str, missing))[0]} isn't this household's")
    if write.assumptions:
        found = await conn.execute(
            select(FACT.c.id).where(
                FACT.c.id.in_(list(write.assumptions)), FACT.c.household_id == household_id
            )
        )
        missing_facts = set(write.assumptions) - set(found.scalars())
        if missing_facts:
            raise ProposalError(f"fact {sorted(map(str, missing_facts))[0]} isn't this household's")
    if write.revises is not None:
        old = await _one(conn, select(DECISION).where(DECISION.c.id == write.revises))
        if old is None or old["household_id"] != household_id:
            raise ProposalError(f"decision {write.revises} isn't this household's")
        if old["status"] != "active" or old["valid_from"] >= write.valid_from:
            raise ProposalError(
                f"decision {write.revises} must be active and start before this one to be revised"
            )


async def _check_people(
    conn: AsyncConnection, household_id: uuid.UUID, people: set[uuid.UUID]
) -> None:
    if not people:
        return
    found = await conn.execute(
        select(PERSON.c.id).where(
            PERSON.c.id.in_(list(people)), PERSON.c.household_id == household_id
        )
    )
    if people - set(found.scalars()):
        raise ProposalError("evidence names a person who isn't in this household")


def _same(kind: str, a: Any, b: Any) -> bool:
    if kind in FACT_KINDS:
        try:
            a, b = canonical_payload(a), canonical_payload(b)
        except PayloadError:
            return False
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


async def propose(
    conn: AsyncConnection,
    *,
    household_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any],
    explanation: str,
    idempotency_key: str,
    evidence: Sequence[Evidence],
    today: date,
    created_at: datetime,
    dream_run_id: uuid.UUID | None = None,
) -> Proposed:
    """Store a pending proposal with its evidence, once per idempotency key. `today` is the
    household's date when it was said (a start date may be it)."""
    if created_at.tzinfo is None:
        raise ProposalError("created_at must carry its time zone (UTC)")
    if kind not in KINDS:
        raise ProposalError(f"{kind!r} isn't a kind of proposal")
    if not explanation.strip() or len(explanation) > MAX_TEXT:
        raise ProposalError(f"an explanation is 1 to {MAX_TEXT} characters")
    if not evidence or len(evidence) > MAX_EVIDENCE:
        raise ProposalError(f"a proposal rests on 1 to {MAX_EVIDENCE} pieces of evidence")
    for item in evidence:
        if item.kind not in EVIDENCE_KINDS:
            raise ProposalError(f"{item.kind!r} isn't a kind of evidence")
        if not item.ref.strip() or not item.quote.strip() or len(item.quote) > MAX_QUOTE:
            raise ProposalError(f"each piece of evidence has a ref and a quote of 1 to {MAX_QUOTE}")
    try:
        _check_payload(kind, payload)
        quotes = [e.quote for e in evidence if e.kind not in NOT_QUOTED]
        missing = unquoted(kind, payload, quotes, today=today)
    except PayloadError as exc:
        raise ProposalError(f"the payload doesn't fit a {kind} proposal: {exc}") from exc
    if missing:
        raise ProposalError(
            "every number in a proposal must appear in its quoted evidence (V-09); not found: "
            + "; ".join(missing)
        )
    async with _atomic(conn):
        household = await _one(
            conn, select(HOUSEHOLD.c.id).where(HOUSEHOLD.c.id == household_id).with_for_update()
        )
        if household is None:
            raise ProposalError(f"household {household_id} doesn't exist")
        await _check_people(conn, household_id, {e.person_id for e in evidence if e.person_id})
        existing = await _one(
            conn, select(PROPOSAL).where(PROPOSAL.c.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if (
                existing["household_id"] == household_id
                and existing["kind"] == kind
                and _same(kind, existing["payload"], payload)
            ):
                return Proposed(existing["id"], created=False)
            if existing["household_id"] != household_id:
                raise ProposalConflict("that idempotency key is already used")
            raise ProposalConflict(
                "something else was already proposed from the same words "
                f"(proposal {existing['id']}, {existing['status']})"
            )
        await _check_rows(conn, household_id, kind, payload)
        proposal_id = uuid.uuid4()
        inserted = await conn.execute(
            insert(PROPOSAL)
            .values(
                id=proposal_id,
                household_id=household_id,
                dream_run_id=dream_run_id,
                kind=kind,
                payload=payload,
                explanation=explanation.strip(),
                status="pending",
                idempotency_key=idempotency_key,
                created_at=created_at,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(PROPOSAL.c.id)
        )
        if inserted.first() is None:  # another writer won the key since we looked
            raise ProposalConflict("the same proposal is being made right now; try again")
        await conn.execute(
            EVIDENCE.insert(),
            [
                {
                    "id": uuid.uuid4(),
                    "proposal_id": proposal_id,
                    "kind": e.kind,
                    "ref": e.ref,
                    "person_id": e.person_id,
                    "quote": e.quote,
                }
                for e in evidence
            ],
        )
    return Proposed(proposal_id, created=True)


# --- Deciding -------------------------------------------------------------------------------


async def _adult(conn: AsyncConnection, household_id: uuid.UUID, person_id: uuid.UUID) -> None:
    person = await _one(
        conn, select(PERSON.c.household_id, PERSON.c.role).where(PERSON.c.id == person_id)
    )
    if person is None or person["household_id"] != household_id:
        raise ProposalError(f"person {person_id} isn't in this household")
    if person["role"] != "adult":
        raise ProposalError("only an adult of the household decides on a proposal")


async def _locked(
    conn: AsyncConnection, proposal_ids: Sequence[uuid.UUID]
) -> tuple[uuid.UUID, list[Any]]:
    """The proposals, locked, after their household's row: the same order the fact store locks
    in, so two approvals can't deadlock."""
    ids = list(dict.fromkeys(proposal_ids))
    if not ids or len(ids) > MAX_BATCH:
        raise ProposalError(f"decide on 1 to {MAX_BATCH} proposals at a time")
    households = set(
        (
            await conn.execute(select(PROPOSAL.c.household_id).where(PROPOSAL.c.id.in_(ids)))
        ).scalars()
    )
    if len(households) != 1:
        raise ProposalError("no such proposal" if not households else "proposals of two households")
    (household_id,) = households
    await conn.execute(
        select(HOUSEHOLD.c.id).where(HOUSEHOLD.c.id == household_id).with_for_update()
    )
    rows = list(
        (
            await conn.execute(
                select(PROPOSAL)
                .where(PROPOSAL.c.id.in_(ids))
                .order_by(PROPOSAL.c.id)
                .with_for_update()
            )
        ).mappings()
    )
    if len(rows) != len(ids):
        raise ProposalError("no such proposal")
    return household_id, rows


async def written_by(conn: AsyncConnection, proposal_id: uuid.UUID) -> tuple[Written, ...]:
    """What an approved proposal wrote: its fact, life event or decision."""
    found: list[Written] = []
    for table, t in (("fact", FACT), ("life_event", LIFE_EVENT), ("decision", DECISION)):
        ids = (await conn.execute(select(t.c.id).where(t.c.proposal_id == proposal_id))).scalars()
        found += [Written(table, row_id) for row_id in ids]
    if not found:  # a retraction marks the fact it names rather than writing a row
        row = await _one(
            conn, select(PROPOSAL.c.kind, PROPOSAL.c.payload).where(PROPOSAL.c.id == proposal_id)
        )
        if row is not None and row["kind"] == "retract_fact":
            found.append(Written("fact", uuid.UUID(row["payload"]["fact_id"])))
    return tuple(found)


async def _source(conn: AsyncConnection, proposal: Any) -> tuple[SourceKind, str]:
    """Where a fact written on approval came from: the turn it was said in (or the first piece of
    evidence), from dreaming when dreaming proposed it."""
    rows = list(
        await conn.execute(
            select(EVIDENCE.c.kind, EVIDENCE.c.ref)
            .where(EVIDENCE.c.proposal_id == proposal["id"])
            .order_by(EVIDENCE.c.kind != "turn", EVIDENCE.c.id)
        )
    )
    if not rows:
        raise ProposalError(f"proposal {proposal['id']} has no evidence to source its fact")
    kind: SourceKind = "dreaming" if proposal["dream_run_id"] is not None else "session"
    return kind, rows[0].ref


async def _write_fact(conn: AsyncConnection, proposal: Any, decided_at: datetime) -> Written:
    write = parse_fact(proposal["kind"], proposal["payload"])
    if write.life_event_id is not None:
        event = await _one(
            conn,
            select(LIFE_EVENT.c.id).where(
                LIFE_EVENT.c.id == write.life_event_id,
                LIFE_EVENT.c.household_id == proposal["household_id"],
            ),
        )
        if event is None:
            raise ProposalError(
                f"proposal {proposal['id']} belongs to a life event of this household "
                "that isn't approved yet: approve the event with it"
            )
    source_kind, source_ref = await _source(conn, proposal)
    new = NewFact(
        household_id=proposal["household_id"],
        entity_id=write.entity_id,
        attribute=write.attribute,
        value=write.value,
        valid_from=write.valid_from,
        source_kind=source_kind,
        source_ref=source_ref,
        valid_to=write.valid_to,
        life_event_id=write.life_event_id,
    )
    if write.replaces is None:
        row = await record_fact(conn, new, proposal_id=proposal["id"], recorded_at=decided_at)
    else:
        row = await replace_fact(
            conn, write.replaces, new, proposal_id=proposal["id"], recorded_at=decided_at
        )
    return Written("fact", row.id)


async def _write_life_event(conn: AsyncConnection, proposal: Any, decided_at: datetime) -> Written:
    event = parse_life_event(proposal["payload"])
    await conn.execute(
        LIFE_EVENT.insert().values(
            id=event.id,
            household_id=proposal["household_id"],
            kind=event.kind,
            description=event.description,
            occurs_on=event.occurs_on,
            recorded_at=decided_at,
            source_ref=event.source_ref,
            proposal_id=proposal["id"],
        )
    )
    return Written("life_event", event.id)


async def _write_decision(conn: AsyncConnection, proposal: Any) -> Written:
    household_id = proposal["household_id"]
    write = parse_decision(proposal["payload"], DECISION_TAGS)
    await _check_decision_rows(conn, household_id, write)
    await conn.execute(
        DECISION.insert().values(
            id=write.id,
            household_id=household_id,
            session_id=write.session_id,
            question=write.question,
            chosen_option_id=write.chosen_option.id,
            reasoning=write.reasoning,
            valid_from=write.valid_from,
            valid_to=None,
            status="active",
            replaced_by=None,
            outcome=None,
            proposal_id=proposal["id"],
        )
    )
    await conn.execute(
        OPTION.insert(),
        [
            {
                "id": o.id,
                "decision_id": write.id,
                "label": o.label,
                "calc_run_id": o.calc_run_id,
                "rejected_reason": o.rejected_reason,
                "tags": list(o.tags),
            }
            for o in write.options
        ],
    )
    if write.assumptions:
        await conn.execute(
            ASSUMPTION.insert(),
            [{"decision_id": write.id, "fact_id": f} for f in write.assumptions],
        )
    if write.revises is not None:
        await conn.execute(
            update(DECISION)
            .where(DECISION.c.id == write.revises, DECISION.c.status == "active")
            .values(status="revised", valid_to=write.valid_from, replaced_by=write.id)
        )
    if write.plan_id is not None:
        previous = (
            (
                await conn.execute(
                    select(PLAN.c.id).where(
                        PLAN.c.household_id == household_id,
                        PLAN.c.status == "accepted",
                        PLAN.c.id != write.plan_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for old in previous:
            await conn.execute(
                update(PLAN)
                .where(PLAN.c.id == old)
                .values(status="replaced", replaced_by=write.plan_id)
            )
        await conn.execute(
            update(PLAN)
            .where(PLAN.c.id == write.plan_id)
            .values(status="accepted", replaces=previous[0] if previous else None)
        )
    return Written("decision", write.id)


async def approve(
    conn: AsyncConnection,
    proposal_ids: Sequence[uuid.UUID],
    *,
    person_id: uuid.UUID,
    decided_at: datetime,
) -> list[Decided]:
    """Approve the proposals and write what each names, all in one transaction: if any write is
    refused, none is made. A proposal that is already approved is left as it is."""
    if decided_at.tzinfo is None:
        raise ProposalError("decided_at must carry its time zone (UTC)")
    results: list[Decided] = []
    async with _atomic(conn):
        household_id, rows = await _locked(conn, proposal_ids)
        await _adult(conn, household_id, person_id)
        for row in sorted(rows, key=lambda r: (PHASE[r["kind"]], str(r["id"]))):
            if row["status"] == "approved":
                results.append(
                    Decided(
                        row["id"], row["kind"], "approved", True, await written_by(conn, row["id"])
                    )
                )
                continue
            if row["status"] != "pending":
                raise ProposalError(
                    f"proposal {row['id']} is {row['status']}; it can't be approved"
                )
            if row["kind"] == "promote":
                raise ProposalError(
                    "promotion comes with its second confirmation (Phase 4, task 4)"
                )
            await conn.execute(
                update(PROPOSAL)
                .where(PROPOSAL.c.id == row["id"], PROPOSAL.c.status == "pending")
                .values(status="approved", decided_by_person_id=person_id, decided_at=decided_at)
            )
            try:
                if row["kind"] in FACT_KINDS:
                    written = await _write_fact(conn, row, decided_at)
                elif row["kind"] == "retract_fact":
                    fact_id, reason = parse_retract(row["payload"])
                    await retract_fact(
                        conn, fact_id, reason=reason, proposal_id=row["id"], retracted_at=decided_at
                    )
                    written = Written("fact", fact_id)
                elif row["kind"] == "life_event":
                    written = await _write_life_event(conn, row, decided_at)
                else:
                    written = await _write_decision(conn, row)
            except (FactStoreError, PayloadError) as exc:
                raise ProposalError(f"proposal {row['id']} can't be written: {exc}") from exc
            except IntegrityError:
                # An id the payload chose is already taken (a life event, decision or option).
                raise ProposalError(
                    f"proposal {row['id']} can't be written: an id it names is already used"
                ) from None
            results.append(Decided(row["id"], row["kind"], "approved", False, (written,)))
    return results


async def reject(
    conn: AsyncConnection,
    proposal_ids: Sequence[uuid.UUID],
    *,
    person_id: uuid.UUID,
    decided_at: datetime,
) -> list[Decided]:
    """Reject pending proposals: nothing is written. Rejecting one already rejected changes
    nothing; an approved one stays approved (a mistake is then retracted, never undone)."""
    if decided_at.tzinfo is None:
        raise ProposalError("decided_at must carry its time zone (UTC)")
    results: list[Decided] = []
    async with _atomic(conn):
        household_id, rows = await _locked(conn, proposal_ids)
        await _adult(conn, household_id, person_id)
        for row in rows:
            if row["status"] == "rejected":
                results.append(Decided(row["id"], row["kind"], "rejected", True))
                continue
            if row["status"] != "pending":
                raise ProposalError(
                    f"proposal {row['id']} is {row['status']}; only a pending one can be rejected"
                )
            await conn.execute(
                update(PROPOSAL)
                .where(PROPOSAL.c.id == row["id"], PROPOSAL.c.status == "pending")
                .values(status="rejected", decided_by_person_id=person_id, decided_at=decided_at)
            )
            results.append(Decided(row["id"], row["kind"], "rejected", False))
    return results


# --- Reading --------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceView:
    kind: str
    ref: str
    quote: str
    said_by: str | None


@dataclass(frozen=True)
class ProposalView:
    id: uuid.UUID
    household_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    explanation: str
    status: Status
    created_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    from_dreaming: bool
    evidence: tuple[EvidenceView, ...]
    written: tuple[Written, ...]


async def list_proposals(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    *,
    status: Status | None = None,
    proposal_ids: Sequence[uuid.UUID] | None = None,
    limit: int = 100,
) -> list[ProposalView]:
    """The household's proposals, newest first, each with its evidence, who decided and when, and
    what an approved one wrote."""
    query = (
        select(PROPOSAL, PERSON.c.display_name.label("decided_by"))
        .outerjoin(PERSON, PERSON.c.id == PROPOSAL.c.decided_by_person_id)
        .where(PROPOSAL.c.household_id == household_id)
        .order_by(PROPOSAL.c.created_at.desc(), PROPOSAL.c.id)
        .limit(limit)
    )
    if status is not None:
        query = query.where(PROPOSAL.c.status == status)
    if proposal_ids is not None:
        query = query.where(PROPOSAL.c.id.in_(list(proposal_ids)))
    rows = list((await conn.execute(query)).mappings())
    ids = [r["id"] for r in rows]
    evidence: dict[uuid.UUID, list[EvidenceView]] = {i: [] for i in ids}
    if ids:
        found = await conn.execute(
            select(EVIDENCE, PERSON.c.display_name)
            .outerjoin(PERSON, PERSON.c.id == EVIDENCE.c.person_id)
            .where(EVIDENCE.c.proposal_id.in_(ids))
            .order_by(EVIDENCE.c.proposal_id, EVIDENCE.c.kind, EVIDENCE.c.ref, EVIDENCE.c.id)
        )
        for e in found.mappings():
            evidence[e["proposal_id"]].append(
                EvidenceView(e["kind"], e["ref"], e["quote"], e["display_name"])
            )
    views = []
    for r in rows:
        written = await written_by(conn, r["id"]) if r["status"] == "approved" else ()
        views.append(
            ProposalView(
                r["id"],
                r["household_id"],
                r["kind"],
                r["payload"],
                r["explanation"],
                r["status"],
                r["created_at"],
                r["decided_by"],
                r["decided_at"],
                r["dream_run_id"] is not None,
                tuple(evidence[r["id"]]),
                written,
            )
        )
    return views
