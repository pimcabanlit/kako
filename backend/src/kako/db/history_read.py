"""What the timeline and decisions screens read: the household's story and its decisions.

Reads only, and only the household's rows. Every fact in every status (nothing is overwritten, so
a replaced value and a corrected one are still here), the life events, the decisions with every
option and the facts each rests on, the plans and the sessions. The words come from
`planning/timeline.py` and `planning/why.py`; "to revisit" from `decisions/revisit.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.agents.present import day, fact_value
from kako.db.fact_store import load_entities, load_facts
from kako.db.models import (
    Decision,
    DecisionAssumption,
    DecisionOption,
    Household,
    LifeEvent,
    Person,
    Plan,
    Proposal,
    ProposalEvidence,
    Session,
    SessionTurn,
)
from kako.db.plan_read import list_plans
from kako.db.provenance import decided_by, provenance
from kako.decisions.revisit import to_revisit
from kako.decisions.tags import TAG_WORDS
from kako.facts.model import EntityRow, FactRow
from kako.planning.timeline import (
    DecisionIn,
    LifeEventIn,
    PlanIn,
    SessionIn,
    Source,
    Timeline,
    events_of,
    things_of,
)
from kako.planning.why import ChangedFact, changed_fact, fact_title
from kako.upkeep.sentences import PHRASES

HOUSEHOLD = cast(Table, Household.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
ASSUMPTION = cast(Table, DecisionAssumption.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
EVIDENCE = cast(Table, ProposalEvidence.__table__)
PERSON = cast(Table, Person.__table__)
PLAN = cast(Table, Plan.__table__)
SESSION = cast(Table, Session.__table__)
SESSION_TURN = cast(Table, SessionTurn.__table__)


@dataclass(frozen=True)
class OptionView:
    label: str
    chosen: bool
    reason: str | None  # why it wasn't chosen
    leans: tuple[str, ...]  # what its tags say: "keeps cash on hand"


@dataclass(frozen=True)
class RestsOn:
    title: str  # "Mara's salary (take-home pay a month)"
    thing: str  # what it is about: "Mara's salary", or "The household" for its own rules
    kind: str  # income, expense, debt, account, goal, household
    words: str  # what the value is: "take-home pay a month"
    value: str
    valid_from: date
    moved: bool  # replaced or corrected since


@dataclass(frozen=True)
class DecisionView:
    id: uuid.UUID
    question: str
    chosen: str
    reasoning: str
    quote: str | None  # the household's own words
    said_by: str | None
    decided_by: str | None
    decided_at: datetime | None
    session_id: uuid.UUID
    session_title: str
    on: date
    status: str  # active, revised, reversed
    valid_to: date | None
    replaced_by: uuid.UUID | None
    outcome: str | None
    plan_id: uuid.UUID | None  # the plan it accepted, if any
    options: tuple[OptionView, ...]
    rests_on: tuple[RestsOn, ...]
    revisit: tuple[ChangedFact, ...]  # the facts that moved, for an active decision


@dataclass(frozen=True)
class Decisions:
    as_of: date
    decisions: tuple[DecisionView, ...]  # newest first


async def _household(conn: AsyncConnection, household_id: uuid.UUID) -> tuple[date, ZoneInfo]:
    row = (
        await conn.execute(
            select(HOUSEHOLD.c.as_of_date, HOUSEHOLD.c.timezone).where(
                HOUSEHOLD.c.id == household_id
            )
        )
    ).one()
    return row[0], ZoneInfo(row[1])


async def _assumed(
    conn: AsyncConnection, decision_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    assumed: dict[uuid.UUID, list[uuid.UUID]] = {d: [] for d in decision_ids}
    if decision_ids:
        for decision_id, fact_id in await conn.execute(
            select(ASSUMPTION.c.decision_id, ASSUMPTION.c.fact_id).where(
                ASSUMPTION.c.decision_id.in_(list(decision_ids))
            )
        ):
            assumed[decision_id].append(fact_id)
    return assumed


async def _decision_rows(conn: AsyncConnection, household_id: uuid.UUID) -> list[dict[str, object]]:
    rows = await conn.execute(
        select(
            DECISION.c.id,
            DECISION.c.question,
            DECISION.c.reasoning,
            DECISION.c.chosen_option_id,
            DECISION.c.valid_from,
            DECISION.c.valid_to,
            DECISION.c.status,
            DECISION.c.replaced_by,
            DECISION.c.outcome,
            DECISION.c.proposal_id,
            DECISION.c.session_id,
            SESSION.c.title.label("session_title"),
            PROPOSAL.c.payload,
            PROPOSAL.c.decided_at,
        )
        .join(SESSION, SESSION.c.id == DECISION.c.session_id)
        .join(PROPOSAL, PROPOSAL.c.id == DECISION.c.proposal_id)
        .where(DECISION.c.household_id == household_id)
        .order_by(DECISION.c.valid_from.desc(), PROPOSAL.c.decided_at.desc(), DECISION.c.id)
    )
    return [dict(r) for r in rows.mappings()]


async def read_decisions(conn: AsyncConnection, household_id: uuid.UUID) -> Decisions:
    """Every decision of the household, newest first, with its options, the facts it rests on, and
    what has moved under it since."""
    as_of, _ = await _household(conn, household_id)
    heads = await _decision_rows(conn, household_id)
    if not heads:
        return Decisions(as_of, ())
    ids = [cast(uuid.UUID, d["id"]) for d in heads]
    entities = await load_entities(conn, household_id)
    facts = await load_facts(conn, household_id)
    by_entity = {e.id: e for e in entities}
    by_id = {f.id: f for f in facts}
    options: dict[uuid.UUID, list[dict[str, object]]] = {}
    for row in (
        await conn.execute(
            select(OPTION).where(OPTION.c.decision_id.in_(ids)).order_by(OPTION.c.label)
        )
    ).mappings():
        options.setdefault(row["decision_id"], []).append(dict(row))
    assumed = await _assumed(conn, ids)
    active = {d["id"] for d in heads if d["status"] == "active"}
    moved = to_revisit({d: f for d, f in assumed.items() if d in active}, facts)
    proposals = [cast(uuid.UUID, d["proposal_id"]) for d in heads]
    decided, _ = await decided_by(conn, proposals)
    quotes: dict[uuid.UUID, tuple[str, str | None]] = {}
    for pid, quote, name in await conn.execute(
        select(EVIDENCE.c.proposal_id, EVIDENCE.c.quote, PERSON.c.display_name)
        .outerjoin(PERSON, PERSON.c.id == EVIDENCE.c.person_id)
        .where(EVIDENCE.c.proposal_id.in_(proposals))
        .order_by(EVIDENCE.c.id)
    ):
        quotes.setdefault(pid, (quote, name))
    out: list[DecisionView] = []
    for d in heads:
        decision_id = cast(uuid.UUID, d["id"])
        mine = options.get(decision_id, [])
        chosen_id = d["chosen_option_id"]
        payload = cast(Mapping[str, object], d["payload"] or {})
        plan = payload.get("plan_id")
        quote, said_by = quotes.get(cast(uuid.UUID, d["proposal_id"]), (None, None))
        who = decided.get(cast(uuid.UUID, d["proposal_id"]))
        changed_ids = {c.old.id for c in moved.get(decision_id, ()) if c.old is not None}
        rests = sorted(
            (by_id[f] for f in assumed.get(decision_id, []) if f in by_id),
            key=lambda f: fact_title(f, by_entity.get(f.entity_id) if f.entity_id else None),
        )
        out.append(
            DecisionView(
                id=decision_id,
                question=cast(str, d["question"]),
                chosen=next((cast(str, o["label"]) for o in mine if o["id"] == chosen_id), ""),
                reasoning=cast(str, d["reasoning"]),
                quote=quote,
                said_by=said_by,
                decided_by=who.approved_by if who else None,
                decided_at=who.approved_at if who else None,
                session_id=cast(uuid.UUID, d["session_id"]),
                session_title=cast(str, d["session_title"]),
                on=cast(date, d["valid_from"]),
                status=cast(str, d["status"]),
                valid_to=cast(date | None, d["valid_to"]),
                replaced_by=cast(uuid.UUID | None, d["replaced_by"]),
                outcome=cast(str | None, d["outcome"]),
                plan_id=uuid.UUID(str(plan)) if plan else None,
                options=tuple(
                    OptionView(
                        label=cast(str, o["label"]),
                        chosen=o["id"] == chosen_id,
                        reason=cast(str | None, o["rejected_reason"]),
                        leans=tuple(TAG_WORDS.get(t, t) for t in cast(list[str], o["tags"] or [])),
                    )
                    for o in sorted(mine, key=lambda o: (o["id"] != chosen_id, str(o["label"])))
                ),
                rests_on=tuple(
                    _rests_on(
                        f,
                        by_entity.get(f.entity_id) if f.entity_id else None,
                        moved=f.id in changed_ids,
                    )
                    for f in rests
                ),
                revisit=tuple(changed_fact(c, by_entity) for c in moved.get(decision_id, ())),
            )
        )
    return Decisions(as_of, tuple(out))


def _rests_on(fact: FactRow, entity: EntityRow | None, *, moved: bool) -> RestsOn:
    return RestsOn(
        title=fact_title(fact, entity),
        thing=entity.name if entity is not None else "The household",
        kind=entity.kind if entity is not None else "household",
        words=PHRASES.get(fact.attribute, fact.attribute),
        value=fact_value(fact),
        valid_from=fact.valid_from,
        moved=moved,
    )


async def read_timeline(conn: AsyncConnection, household_id: uuid.UUID) -> Timeline:
    """The household's story: what happened, newest first, and each thing's values over time."""
    as_of, zone = await _household(conn, household_id)
    entities: list[EntityRow] = await load_entities(conn, household_id)
    facts: list[FactRow] = await load_facts(conn, household_id)
    found = await provenance(conn, facts)
    sources = {k: Source(v.source, v.shared_on, v.approved_by) for k, v in found.items()}

    life_rows = list(
        (
            await conn.execute(
                select(LIFE_EVENT)
                .where(LIFE_EVENT.c.household_id == household_id)
                .order_by(LIFE_EVENT.c.occurs_on, LIFE_EVENT.c.id)
            )
        ).mappings()
    )
    life_decided, _ = await decided_by(conn, [r["proposal_id"] for r in life_rows])
    conversations = {str(r["source_ref"]).partition(":")[0] for r in life_rows}
    titles = dict(
        (
            await conn.execute(
                select(SESSION.c.meko_conversation_id, SESSION.c.title).where(
                    SESSION.c.meko_conversation_id.in_(conversations)
                )
            )
        ).all()
    )
    # A life event's own source_ref may be just its turn's seed; the facts it caused name the
    # session, so their words say where it was told when they can.
    told: dict[uuid.UUID, str] = {}
    for f in sorted(facts, key=lambda f: f.recorded_at):
        if f.life_event_id is not None and f.life_event_id not in told and f.id in sources:
            told[f.life_event_id] = sources[f.id].words
    life_events = []
    for r in life_rows:
        who = life_decided.get(r["proposal_id"])
        where = titles.get(str(r["source_ref"]).partition(":")[0])
        said = f"Told by {who.said_by}" if who and who.said_by else "Told"
        said += f" in {where}" if where else ""
        if who and who.approved_by and who.approved_at:
            said += f", approved by {who.approved_by} on {_day(who.approved_at, zone)}"
        life_events.append(
            LifeEventIn(
                r["id"],
                r["kind"],
                r["description"],
                r["occurs_on"],
                told.get(r["id"], said),
                who.approved_by if who else None,
            )
        )

    heads = await _decision_rows(conn, household_id)
    decided, _ = await decided_by(conn, [cast(uuid.UUID, d["proposal_id"]) for d in heads])
    chosen = dict(
        (
            await conn.execute(
                select(OPTION.c.id, OPTION.c.label).where(
                    OPTION.c.id.in_([d["chosen_option_id"] for d in heads])
                )
            )
        ).all()
    )
    decisions = [
        DecisionIn(
            cast(uuid.UUID, d["id"]),
            cast(str, d["question"]),
            chosen.get(d["chosen_option_id"], ""),
            cast(str, d["session_title"]),
            cast(date, d["valid_from"]),
            decided[cast(uuid.UUID, d["proposal_id"])].approved_by
            if cast(uuid.UUID, d["proposal_id"]) in decided
            else None,
        )
        for d in heads
    ]
    active = [cast(uuid.UUID, d["id"]) for d in heads if d["status"] == "active"]
    revisit = to_revisit(await _assumed(conn, active), facts)

    plans = [
        PlanIn(p.id, p.version, p.status, p.as_of, p.session_title)
        for p in await list_plans(conn, household_id)
    ]
    turns = (
        select(SESSION_TURN.c.session_id, func.count().label("n"))
        .group_by(SESSION_TURN.c.session_id)
        .subquery()
    )
    sessions = [
        SessionIn(r[0], r[1], r[2], r[3] or 0)
        for r in await conn.execute(
            select(SESSION.c.id, SESSION.c.title, SESSION.c.household_date, turns.c.n)
            .outerjoin(turns, turns.c.session_id == SESSION.c.id)
            .where(SESSION.c.household_id == household_id)
        )
    ]
    events = events_of(
        as_of=as_of,
        zone=zone,
        entities=entities,
        facts=facts,
        sources=sources,
        life_events=life_events,
        decisions=decisions,
        plans=plans,
        sessions=sessions,
        revisit=revisit,
    )
    things = things_of(as_of=as_of, entities=entities, facts=facts, sources=sources)
    return Timeline(as_of, events, things)


def _day(at: datetime, zone: ZoneInfo) -> str:
    return day(at.astimezone(zone).date())
