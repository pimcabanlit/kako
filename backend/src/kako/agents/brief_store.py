"""Gathering the brief: Postgres for the household, its facts and its decisions; Meko for one
`context_search` on the household's message; then `render_brief` within the budget.

Reads only. The approved preferences come from the fact store, the record (Pim, Nov 24): a
preference fact shows who approved it and when, and is marked promoted once `meko_link` holds its
promoted memory (Phase 4). Figures never come from Meko.
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
    OptionView,
    ProposalView,
    is_preference,
    render_brief,
)
from kako.db.fact_store import load_entities, snapshot
from kako.db.models import Decision, DecisionOption, Household, MekoLink, Person, Proposal, Session
from kako.engine import Run, compute
from kako.meko.adapter import Context, Meko

HOUSEHOLD = cast(Table, Household.__table__)
PERSON = cast(Table, Person.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
SESSION = cast(Table, Session.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
SEARCH_AGENT = "kako:orchestrator"  # the brief's search is the orchestrator's, once per turn


class BriefStoreError(Exception):
    """The household to brief on doesn't exist."""


async def _approvals(
    conn: AsyncConnection,
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
        .where(PROPOSAL.c.id.in_(list(facts.values())), PROPOSAL.c.status == "approved")
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


async def _decisions(
    conn: AsyncConnection, household_id: uuid.UUID, on: date
) -> tuple[DecisionView, ...]:
    """Active decisions in force on `on`, each with its options."""
    rows = list(
        await conn.execute(
            select(DECISION, SESSION.c.title)
            .join(SESSION, SESSION.c.id == DECISION.c.session_id)
            .where(
                DECISION.c.household_id == household_id,
                DECISION.c.status == "active",
                DECISION.c.valid_from <= on,
                or_(DECISION.c.valid_to.is_(None), DECISION.c.valid_to > on),
            )
            .order_by(DECISION.c.valid_from, DECISION.c.id)
        )
    )
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


async def _pending(conn: AsyncConnection, household_id: uuid.UUID) -> tuple[ProposalView, ...]:
    rows = await conn.execute(
        select(PROPOSAL.c.id, PROPOSAL.c.kind, PROPOSAL.c.explanation, PROPOSAL.c.created_at)
        .where(and_(PROPOSAL.c.household_id == household_id, PROPOSAL.c.status == "pending"))
        .order_by(PROPOSAL.c.created_at, PROPOSAL.c.id)
    )
    return tuple(ProposalView(r.id, r.kind, r.explanation, r.created_at) for r in rows)


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
) -> tuple[Brief, Run]:
    """The brief for one turn, and the engine run it describes. At most one Meko call: a
    `context_search` on the household's message (none when there is no message, no Meko, or a
    search limit of 0)."""
    household = (
        await conn.execute(
            select(HOUSEHOLD.c.name, HOUSEHOLD.c.timezone).where(HOUSEHOLD.c.id == household_id)
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
    if meko is not None and conversation_id and message.strip() and search_limit > 0:
        context = await meko.search_context(
            conversation_id, message, agent_id=SEARCH_AGENT, limit=search_limit
        )
    inputs = BriefInputs(
        household_name=household.name,
        people=people,
        entities=tuple(entities),
        snapshot=snap,
        run=run,
        approvals=await _approvals(conn, preferences, dreamed, ZoneInfo(household.timezone)),
        decisions=await _decisions(conn, household_id, on),
        proposals=await _pending(conn, household_id),
        message=message,
        context=context,
    )
    return render_brief(inputs, budget), run
