"""Gathering a replan: the changes approved in this session, and what they touch.

Reads only, and only this household's rows. A session's changes are the proposals made from its
turns (their idempotency key starts with the session's id, `facts.proposals.idempotency_key`) that
a person approved, as known at the turn's `known_at`. The replan compares the turn's run with the
run the household last decided on, recomputed from the facts as Kako knew them when it decided:
facts are never overwritten, so that run is exactly the one it saw (`agents.replan`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.agents.brief import DecisionView
from kako.agents.present import day
from kako.agents.replan import Replan, Revisit
from kako.db.fact_store import load_facts
from kako.db.models import Decision, DecisionAssumption, DecisionOption, Proposal, Session
from kako.engine import Run, compute
from kako.engine.diff import diff
from kako.facts.model import EntityRow
from kako.facts.proposals import FACT_KINDS
from kako.facts.snapshot import take_snapshot

PROPOSAL = cast(Table, Proposal.__table__)
DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
ASSUMPTION = cast(Table, DecisionAssumption.__table__)
SESSION = cast(Table, Session.__table__)
CHANGE_KINDS = ("life_event", "retract_fact", *sorted(FACT_KINDS))
JUST_BEFORE = timedelta(microseconds=1)


@dataclass(frozen=True)
class SessionChanges:
    """What a person approved from this session's turns, as known then."""

    on: date  # the latest day one of them takes effect (the replan's date)
    first_decided_at: datetime  # before it, the session had changed nothing


async def session_changes(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    session_id: uuid.UUID,
    session_on: date,
    known_at: datetime | None,
) -> SessionChanges | None:
    """The changes approved from this session's turns, or None when there are none."""
    query = select(PROPOSAL.c.kind, PROPOSAL.c.payload, PROPOSAL.c.decided_at).where(
        PROPOSAL.c.household_id == household_id,
        PROPOSAL.c.status == "approved",
        PROPOSAL.c.kind.in_(CHANGE_KINDS),
        PROPOSAL.c.idempotency_key.startswith(f"{session_id}:", autoescape=True),
    )
    if known_at is not None:
        query = query.where(PROPOSAL.c.decided_at <= known_at)
    rows = list(await conn.execute(query))
    if not rows:
        return None
    on = session_on
    for kind, payload, _ in rows:
        when = payload.get("occurs_on") if kind == "life_event" else payload.get("valid_from")
        if isinstance(when, str):
            on = max(on, date.fromisoformat(when))
    return SessionChanges(on, min(r.decided_at for r in rows))


async def last_decision(
    conn: AsyncConnection, household_id: uuid.UUID, on: date, known_at: datetime | None
) -> tuple[uuid.UUID, date, datetime, str] | None:
    """The household's latest decision on or before `on`, as known then: its id, date, when it
    was approved and how it is named."""
    query = (
        select(
            DECISION.c.id,
            DECISION.c.valid_from,
            PROPOSAL.c.decided_at,
            DECISION.c.question,
            SESSION.c.title,
            OPTION.c.label,
        )
        .join(PROPOSAL, PROPOSAL.c.id == DECISION.c.proposal_id)
        .join(SESSION, SESSION.c.id == DECISION.c.session_id)
        .join(OPTION, OPTION.c.id == DECISION.c.chosen_option_id)
        .where(DECISION.c.household_id == household_id, DECISION.c.valid_from <= on)
        .order_by(DECISION.c.valid_from.desc(), PROPOSAL.c.decided_at.desc(), DECISION.c.id)
        .limit(1)
    )
    if known_at is not None:
        query = query.where(PROPOSAL.c.decided_at <= known_at)
    row = (await conn.execute(query)).first()
    if row is None:
        return None
    named = f"the decision of {day(row.valid_from)} in {row.title} ({row.label})"
    return row.id, row.valid_from, row.decided_at, named


async def gather_replan(
    conn: AsyncConnection,
    *,
    household_id: uuid.UUID,
    entities: list[EntityRow],
    run: Run,
    changes: SessionChanges,
    session_on: date,
    decisions: tuple[DecisionView, ...],
    known_at: datetime | None,
) -> Replan:
    """What the session's changes touch: the turn's `run` against the one the household last
    decided on, and the `decisions` in force whose assumptions changed."""
    facts = await load_facts(conn, household_id)
    last = await last_decision(conn, household_id, run.as_of, known_at)
    if last is not None:
        decision_id, on, decided_at, since = last
    else:
        decision_id, on = None, session_on
        decided_at, since = (
            changes.first_decided_at - JUST_BEFORE,
            "this session, before its changes",
        )
    before = compute(take_snapshot(household_id, facts, on, decided_at), entities)
    ids = [d.id for d in decisions]
    assumed: dict[uuid.UUID, list[uuid.UUID]] = {i: [] for i in ids}
    if ids:
        rows = await conn.execute(
            select(ASSUMPTION.c.decision_id, ASSUMPTION.c.fact_id).where(
                ASSUMPTION.c.decision_id.in_(ids)
            )
        )
        for decision, fact in rows:
            assumed[decision].append(fact)
    found = diff(before, run, facts, assumed)
    views = {d.id: d for d in decisions}
    revisit = tuple(
        Revisit(
            r.decision_id,
            views[r.decision_id].question,
            views[r.decision_id].chosen,
            views[r.decision_id].session_title,
            day(views[r.decision_id].valid_from),
            r.facts,
        )
        for r in found.decisions
    )
    return Replan(since, decision_id, before, found, revisit)
