"""Gathering the brief: Postgres for the household, its facts and its decisions; Meko for one
`context_search` on the household's message; then `render_brief` within the budget.

Reads only, and only this household's rows. The approved preferences come from the fact store, the
record (Pim, Nov 24): a preference fact shows who approved it and when, and is marked promoted once
`meko_link` holds its promoted memory (Phase 4). A memory found by the search is marked approved
only when `meko_link` ties it to one of this household's facts or decisions; Meko's own metadata
can be written by any client of the datapack, so it never decides that. The search runs only in a
conversation of this household's sessions, on the household's datapack. Figures never come from
Meko.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import Table, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.agents.brief import (
    Approval,
    Brief,
    BriefInputs,
    DecisionView,
    LifeEventView,
    OptionView,
    ProposalView,
    is_preference,
    render_brief,
)
from kako.agents.replan_store import SessionChanges, gather_replan
from kako.db.fact_store import load_entities, snapshot
from kako.db.models import (
    Decision,
    DecisionOption,
    Fact,
    Household,
    LifeEvent,
    MekoLink,
    Person,
    Proposal,
    Session,
)
from kako.engine import Run, compute
from kako.meko.adapter import Context, Meko

HOUSEHOLD = cast(Table, Household.__table__)
PERSON = cast(Table, Person.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
SESSION = cast(Table, Session.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
MAX_LIFE_EVENTS = 5  # the most recent ones the brief shows
FACT = cast(Table, Fact.__table__)
BUDGET_RANGE = range(500, 20_001)  # KAKO_BRIEF_TOKEN_BUDGET's bounds
SEARCH_LIMIT_RANGE = range(0, 11)  # KAKO_BRIEF_SEARCH_LIMIT's bounds
SEARCH_AGENT = "kako:orchestrator"  # the brief's search is the orchestrator's, once per turn


class BriefStoreError(Exception):
    """The household to brief on doesn't exist."""


async def _approvals(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    facts: dict[uuid.UUID, uuid.UUID],
    dreamed: set[uuid.UUID],
    zone: ZoneInfo,
) -> dict[uuid.UUID, Approval]:
    """For each preference fact (by id) with a proposal: who approved it, when, and why."""
    if not facts:
        return {}
    rows = await conn.execute(
        select(
            PROPOSAL.c.id,
            PROPOSAL.c.explanation,
            PROPOSAL.c.decided_at,
            PROPOSAL.c.dream_run_id,
            PERSON.c.display_name,
        )
        .join(PERSON, PERSON.c.id == PROPOSAL.c.decided_by_person_id)
        .where(
            PROPOSAL.c.household_id == household_id,
            PROPOSAL.c.id.in_(list(facts.values())),
            PROPOSAL.c.status == "approved",
        )
    )
    by_proposal = {r.id: r for r in rows}
    promoted = set(
        (
            await conn.execute(
                select(MEKO_LINK.c.kako_id).where(
                    MEKO_LINK.c.kako_table == "fact",
                    MEKO_LINK.c.kako_id.in_(list(facts)),
                    MEKO_LINK.c.meko_kind == "promoted_memory",
                )
            )
        ).scalars()
    )
    approvals: dict[uuid.UUID, Approval] = {}
    for fact_id, proposal_id in facts.items():
        row = by_proposal.get(proposal_id)
        if row is None:
            continue
        approvals[fact_id] = Approval(
            approved_by=row.display_name,
            approved_at=row.decided_at.astimezone(zone),  # shown in the household's time
            explanation=row.explanation,
            from_dreaming=row.dream_run_id is not None or fact_id in dreamed,
            promoted=fact_id in promoted,
        )
    return approvals


async def _approved_memories(
    conn: AsyncConnection, household_id: uuid.UUID, memory_ids: list[str]
) -> frozenset[str]:
    """The memories `meko_link` ties to this household's facts (not retracted) or decisions."""
    if not memory_ids:
        return frozenset()
    kinds = ("memory", "promoted_memory")
    of_facts = (
        select(MEKO_LINK.c.meko_id)
        .join(FACT, and_(MEKO_LINK.c.kako_table == "fact", FACT.c.id == MEKO_LINK.c.kako_id))
        .where(
            FACT.c.household_id == household_id,
            FACT.c.status != "retracted",
            MEKO_LINK.c.meko_kind.in_(kinds),
            MEKO_LINK.c.meko_id.in_(memory_ids),
        )
    )
    of_decisions = (
        select(MEKO_LINK.c.meko_id)
        .join(
            DECISION,
            and_(MEKO_LINK.c.kako_table == "decision", DECISION.c.id == MEKO_LINK.c.kako_id),
        )
        .where(
            DECISION.c.household_id == household_id,
            MEKO_LINK.c.meko_kind.in_(kinds),
            MEKO_LINK.c.meko_id.in_(memory_ids),
        )
    )
    rows = await conn.execute(of_facts.union(of_decisions))
    return frozenset(rows.scalars())


async def _decisions(
    conn: AsyncConnection, household_id: uuid.UUID, on: date, known_at: datetime | None
) -> tuple[DecisionView, ...]:
    """Decisions in force on `on`, as Kako knew them at `known_at` (now, when None), each with its
    options: approved by then, and not yet revised or reversed by a decision approved by then."""
    made = PROPOSAL.alias("made")
    later = DECISION.alias("later")
    later_made = PROPOSAL.alias("later_made")
    revised_later = (
        select(later_made.c.decided_at)
        .join(later, later.c.proposal_id == later_made.c.id)
        .where(later.c.id == DECISION.c.replaced_by)
        .scalar_subquery()
    )
    in_force = and_(
        DECISION.c.status == "active",
        or_(DECISION.c.valid_to.is_(None), DECISION.c.valid_to > on),
    )
    query = (
        select(DECISION, SESSION.c.title)
        .join(SESSION, SESSION.c.id == DECISION.c.session_id)
        .join(made, made.c.id == DECISION.c.proposal_id)
        .where(DECISION.c.household_id == household_id, DECISION.c.valid_from <= on)
        .order_by(DECISION.c.valid_from, DECISION.c.id)
    )
    if known_at is None:
        query = query.where(in_force)
    else:
        query = query.where(made.c.decided_at <= known_at, or_(in_force, revised_later > known_at))
    rows = list(await conn.execute(query))
    if not rows:
        return ()
    options = list(
        await conn.execute(
            select(OPTION)
            .where(OPTION.c.decision_id.in_([r.id for r in rows]))
            .order_by(OPTION.c.label, OPTION.c.id)
        )
    )
    views = []
    for r in rows:
        mine = [o for o in options if o.decision_id == r.id]
        chosen = next((o.label for o in mine if o.id == r.chosen_option_id), "?")
        views.append(
            DecisionView(
                id=r.id,
                question=r.question,
                chosen=chosen,
                reasoning=r.reasoning,
                valid_from=r.valid_from,
                session_title=r.title,
                options=tuple(OptionView(o.label, o.rejected_reason) for o in mine),
            )
        )
    return tuple(views)


async def _pending(
    conn: AsyncConnection, household_id: uuid.UUID, known_at: datetime | None
) -> tuple[ProposalView, ...]:
    """Proposals waiting for a person at `known_at` (now, when None): made by then and not yet
    decided then."""
    query = (
        select(PROPOSAL.c.id, PROPOSAL.c.kind, PROPOSAL.c.explanation, PROPOSAL.c.created_at)
        .where(PROPOSAL.c.household_id == household_id)
        .order_by(PROPOSAL.c.created_at, PROPOSAL.c.id)
    )
    if known_at is None:
        query = query.where(PROPOSAL.c.status == "pending")
    else:
        query = query.where(
            PROPOSAL.c.created_at <= known_at,
            or_(PROPOSAL.c.status == "pending", PROPOSAL.c.decided_at > known_at),
        )
    rows = await conn.execute(query)
    return tuple(ProposalView(r.id, r.kind, r.explanation, r.created_at) for r in rows)


async def _life_events(
    conn: AsyncConnection, household_id: uuid.UUID, known_at: datetime | None
) -> tuple[LifeEventView, ...]:
    """The household's most recent life events, as known at `known_at`, oldest first."""
    query = (
        select(LIFE_EVENT.c.kind, LIFE_EVENT.c.description, LIFE_EVENT.c.occurs_on)
        .where(LIFE_EVENT.c.household_id == household_id)
        .order_by(LIFE_EVENT.c.occurs_on.desc(), LIFE_EVENT.c.recorded_at.desc())
        .limit(MAX_LIFE_EVENTS)
    )
    if known_at is not None:
        query = query.where(LIFE_EVENT.c.recorded_at <= known_at)
    rows = list(await conn.execute(query))
    return tuple(LifeEventView(r.kind, r.description, r.occurs_on) for r in reversed(rows))


async def _check_meko_scope(
    conn: AsyncConnection,
    meko: Meko,
    household_id: uuid.UUID,
    datapack_id: str | None,
    conversation_id: str,
) -> None:
    """Refuse a search outside the household: another datapack, or another household's
    conversation."""
    if datapack_id is not None and meko.datapack_id != datapack_id:
        raise BriefStoreError("Meko isn't on this household's datapack")
    session = (
        await conn.execute(
            select(SESSION.c.id).where(
                SESSION.c.household_id == household_id,
                SESSION.c.meko_conversation_id == conversation_id,
            )
        )
    ).first()
    if session is None:
        raise BriefStoreError("the conversation isn't one of this household's sessions")


async def gather_brief(
    conn: AsyncConnection,
    meko: Meko | None,
    *,
    household_id: uuid.UUID,
    on: date,
    known_at: datetime | None,
    message: str,
    conversation_id: str | None,
    budget: int,
    search_limit: int = 5,
    run: Run | None = None,
    changes: SessionChanges | None = None,
    session_on: date | None = None,
) -> tuple[Brief, BriefInputs]:
    """The brief for one turn, and what it was rendered from (the snapshot, the engine run it
    describes, the decisions), which the agents' tools read. At most one Meko call: a
    `context_search` on the household's message (none when there is no message, no Meko, or a
    search limit of 0). With `changes` approved in the session (dated `session_on`), the brief
    says what they changed against the plan the household last decided on (`agents.replan`)."""
    if budget not in BUDGET_RANGE or search_limit not in SEARCH_LIMIT_RANGE:
        raise ValueError("the brief's budget or search limit is out of its settings' bounds")
    household = (
        await conn.execute(
            select(HOUSEHOLD.c.name, HOUSEHOLD.c.timezone, HOUSEHOLD.c.meko_datapack_id).where(
                HOUSEHOLD.c.id == household_id
            )
        )
    ).one_or_none()
    if household is None:
        raise BriefStoreError(f"household {household_id} doesn't exist")
    people = tuple(
        (r.display_name, r.role)
        for r in await conn.execute(
            select(PERSON.c.display_name, PERSON.c.role)
            .where(PERSON.c.household_id == household_id)
            .order_by(PERSON.c.role, PERSON.c.display_name)
        )
    )
    entities = await load_entities(conn, household_id)
    snap = await snapshot(conn, household_id, on, known_at)
    if run is None:
        run = compute(snap, entities)
    elif run.snapshot_hash != snap.hash:
        raise BriefStoreError("the run given wasn't computed from this snapshot")
    preferences = {
        f.id: f.proposal_id
        for f in snap.facts
        if is_preference(f.attribute) and f.proposal_id is not None
    }
    dreamed = {f.id for f in snap.facts if f.source_kind == "dreaming"}
    context: Context | None = None
    approved: frozenset[str] = frozenset()
    if meko is not None and conversation_id and message.strip() and search_limit > 0:
        await _check_meko_scope(
            conn, meko, household_id, household.meko_datapack_id, conversation_id
        )
        context = await meko.search_context(
            conversation_id, message, agent_id=SEARCH_AGENT, limit=search_limit
        )
        approved = await _approved_memories(conn, household_id, [m.id for m in context.memories])
    decisions = await _decisions(conn, household_id, on, known_at)
    replan = None
    if changes is not None:
        replan = await gather_replan(
            conn,
            household_id=household_id,
            entities=entities,
            run=run,
            changes=changes,
            session_on=session_on or on,
            decisions=decisions,
            known_at=known_at,
        )
    inputs = BriefInputs(
        household_name=household.name,
        people=people,
        entities=tuple(entities),
        snapshot=snap,
        run=run,
        approvals=await _approvals(
            conn, household_id, preferences, dreamed, ZoneInfo(household.timezone)
        ),
        decisions=decisions,
        proposals=await _pending(conn, household_id, known_at),
        life_events=await _life_events(conn, household_id, known_at),
        replan=replan,
        message=message,
        context=context,
        approved_memories=approved,
    )
    return render_brief(inputs, budget), inputs
