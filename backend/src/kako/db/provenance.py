"""Where each fact came from and who said yes to it, in words, for the plan and timeline screens.

Reads only: the approved proposal behind each fact (who decided, when), who said it in a turn
(`proposal_evidence`), the session it came from (by its Meko conversation, or the session dreaming
read), and when it was shared with every agent in Meko (`meko_link`, a promoted memory).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.agents.present import day
from kako.db.models import DreamRun, MekoLink, Person, Proposal, ProposalEvidence, Session
from kako.facts.model import FactRow

PROPOSAL = cast(Table, Proposal.__table__)
EVIDENCE = cast(Table, ProposalEvidence.__table__)
PERSON = cast(Table, Person.__table__)
SESSION = cast(Table, Session.__table__)
DREAM_RUN = cast(Table, DreamRun.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)


@dataclass(frozen=True)
class Decided:
    """Who approved a proposal and when, and who said it in a turn (if anyone)."""

    approved_by: str | None
    approved_at: datetime | None
    said_by: str | None


@dataclass(frozen=True)
class Provenance:
    source: str  # "From a statement, approved by Jun on Nov 16, 2026"
    shared_on: date | None  # when it was shared with every agent in Meko
    approved_by: str | None = None  # who said yes to it (None for a seed fact)


def source_words(
    fact: FactRow, dreamed_in: str | None, titles: Mapping[str, str], decided: Decided
) -> str:
    """Where a fact came from and who said yes to it, in words."""
    where = dreamed_in or (
        titles.get(fact.source_ref.partition(":")[0]) if fact.source_ref else None
    )
    yes = (
        f"approved by {decided.approved_by} on {day(decided.approved_at.date())}"
        if decided.approved_by and decided.approved_at
        else "approved"
    )
    if fact.source_kind == "seed":
        return "From the household's starting figures"
    if fact.source_kind == "dreaming":
        return f"Learned by dreaming from {where or 'a past session'}, {yes}"
    if fact.source_kind == "session":
        who = f" by {decided.said_by}" if decided.said_by else ""
        return f"Said{who} in {where or 'a session'}, {yes}"
    if fact.source_kind == "statement":
        return f"From a statement, {yes}"
    return f"Entered by the household, {yes}"


async def decided_by(
    conn: AsyncConnection, proposal_ids: Sequence[uuid.UUID]
) -> tuple[dict[uuid.UUID, Decided], dict[uuid.UUID, str]]:
    """Each proposal's approval and speaker, and, for a dreaming proposal, the session dreaming
    read (by title)."""
    decided: dict[uuid.UUID, Decided] = {}
    dreamed: dict[uuid.UUID, str] = {}
    if not proposal_ids:
        return decided, dreamed
    ids = list(dict.fromkeys(proposal_ids))
    said = (
        select(EVIDENCE.c.proposal_id, func.min(PERSON.c.display_name).label("name"))
        .join(PERSON, PERSON.c.id == EVIDENCE.c.person_id)
        .where(EVIDENCE.c.proposal_id.in_(ids), EVIDENCE.c.kind == "turn")
        .group_by(EVIDENCE.c.proposal_id)
        .subquery()
    )
    dreamt = SESSION.alias("dreamt")
    for pid, name, at, said_by, dream_title in await conn.execute(
        select(
            PROPOSAL.c.id,
            PERSON.c.display_name,
            PROPOSAL.c.decided_at,
            said.c.name,
            dreamt.c.title,
        )
        .outerjoin(PERSON, PERSON.c.id == PROPOSAL.c.decided_by_person_id)
        .outerjoin(said, said.c.proposal_id == PROPOSAL.c.id)
        .outerjoin(DREAM_RUN, DREAM_RUN.c.id == PROPOSAL.c.dream_run_id)
        .outerjoin(dreamt, dreamt.c.id == DREAM_RUN.c.session_id)
        .where(PROPOSAL.c.id.in_(ids))
    ):
        decided[pid] = Decided(name, at, said_by)
        if dream_title is not None:
            dreamed[pid] = dream_title
    return decided, dreamed


async def provenance(conn: AsyncConnection, rows: Sequence[FactRow]) -> dict[uuid.UUID, Provenance]:
    """Each fact's source in words, and when it was shared in Meko."""
    if not rows:
        return {}
    decided, dreamed = await decided_by(
        conn, [f.proposal_id for f in rows if f.proposal_id is not None]
    )
    conversations = {f.source_ref.partition(":")[0] for f in rows if f.source_ref}
    titles = {
        conv: title
        for conv, title in await conn.execute(
            select(SESSION.c.meko_conversation_id, SESSION.c.title).where(
                SESSION.c.meko_conversation_id.in_(conversations)
            )
        )
    }
    shared = {
        kako_id: at
        for kako_id, at in await conn.execute(
            select(MEKO_LINK.c.kako_id, func.min(MEKO_LINK.c.created_at))
            .where(
                MEKO_LINK.c.kako_table == "fact",
                MEKO_LINK.c.kako_id.in_([f.id for f in rows]),
                MEKO_LINK.c.meko_kind == "promoted_memory",
            )
            .group_by(MEKO_LINK.c.kako_id)
        )
    }
    nobody = Decided(None, None, None)
    return {
        fact.id: Provenance(
            source=source_words(
                fact,
                dreamed.get(fact.proposal_id) if fact.proposal_id else None,
                titles,
                decided.get(fact.proposal_id, nobody) if fact.proposal_id else nobody,
            ),
            shared_on=shared[fact.id].date() if fact.id in shared else None,
            approved_by=(
                decided.get(fact.proposal_id, nobody).approved_by if fact.proposal_id else None
            ),
        )
        for fact in rows
    }
