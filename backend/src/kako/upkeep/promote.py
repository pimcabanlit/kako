"""Meko upkeep's sharing: what a person approved for sharing, with its second confirmation
(`db/proposal_store.approve`), carried out in Meko (docs/data-model.md, "What Kako keeps in Meko").

- **A preference** goes to the datapack's **collective memory**: its sentence (`sentences.py`) is
  added as `kako:upkeep`'s memory, then promoted, and linked in `meko_link` as a `promoted_memory`
  with the words shared. Promotion can't be undone, so before adding, the promoted memories Meko
  lists are read: one `kako:upkeep` already promoted with the same words (a run stopped before it
  wrote the link) is linked, never promoted twice. A memory Meko didn't promote is deleted again.
- **A decision** goes to the **knowledge base** as a decision record (`records.py`, Markdown),
  linked as a `document` by its upload key. Meko takes the same content once.

What is shared is read from rows that never change once written, so it is what was approved. A
preference replaced, or a decision revised, before upkeep gets to it is no longer shared: it isn't
owed. Each share is its Meko calls, then its link in its own transaction.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import Table, exists, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.db.fact_store import load_entities, load_facts
from kako.db.models import (
    Decision,
    DecisionAssumption,
    DecisionOption,
    Fact,
    Household,
    MekoLink,
    Person,
    Proposal,
    Session,
)
from kako.facts.proposals import parse_promote
from kako.meko.adapter import Meko
from kako.meko.client import MekoError
from kako.upkeep.records import (
    DecisionRecord,
    OptionRecord,
    Revised,
    decision_record,
    record_filename,
)
from kako.upkeep.sentences import fact_sentence

PROPOSAL = cast(Table, Proposal.__table__)
FACT = cast(Table, Fact.__table__)
DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
ASSUMPTION = cast(Table, DecisionAssumption.__table__)
SESSION = cast(Table, Session.__table__)
PERSON = cast(Table, Person.__table__)
HOUSEHOLD = cast(Table, Household.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
SHARED_AS: Final = {"fact": "promoted_memory", "decision": "document"}
# The Meko calls one share can make at most: a preference lists the promoted memories, adds its
# memory, promotes it, and deletes it again if Meko didn't; a decision record is one upload.
SHARE_CALLS: Final = {"fact": 4, "decision": 1}


@dataclass(frozen=True)
class Share:
    """An approved promotion that Meko doesn't hold yet."""

    proposal_id: uuid.UUID
    target: Literal["fact", "decision"]
    row_id: uuid.UUID


async def shares_owed(conn: AsyncConnection, household_id: uuid.UUID) -> list[Share]:
    """The household's approved promotions with no link to what Meko holds, oldest approval
    first, leaving out a preference or decision that no longer holds."""
    rows = await conn.execute(
        select(PROPOSAL.c.id, PROPOSAL.c.payload)
        .where(
            PROPOSAL.c.household_id == household_id,
            PROPOSAL.c.kind == "promote",
            PROPOSAL.c.status == "approved",
        )
        .order_by(PROPOSAL.c.decided_at, PROPOSAL.c.id)
    )
    owed: list[Share] = []
    for proposal_id, payload in rows:
        target, row_id = parse_promote(payload)
        if await _shared(conn, target, row_id) or not await _holds(
            conn, household_id, target, row_id
        ):
            continue
        owed.append(Share(proposal_id, cast(Literal["fact", "decision"], target), row_id))
    return owed


async def _shared(conn: AsyncConnection, target: str, row_id: uuid.UUID) -> bool:
    found = await conn.execute(
        select(
            exists().where(
                MEKO_LINK.c.kako_table == target,
                MEKO_LINK.c.kako_id == row_id,
                MEKO_LINK.c.meko_kind == SHARED_AS[target],
            )
        )
    )
    return bool(found.scalar_one())


async def _holds(
    conn: AsyncConnection, household_id: uuid.UUID, target: str, row_id: uuid.UUID
) -> bool:
    if target == "fact":
        query = select(FACT.c.id).where(
            FACT.c.id == row_id,
            FACT.c.household_id == household_id,
            FACT.c.status == "active",
            FACT.c.valid_to.is_(None),
        )
    else:
        query = select(DECISION.c.id).where(
            DECISION.c.id == row_id,
            DECISION.c.household_id == household_id,
            DECISION.c.status == "active",
        )
    return (await conn.execute(query)).first() is not None


async def share(
    engine: AsyncEngine,
    meko: Meko,
    household_id: uuid.UUID,
    conversation_id: str,
    item: Share,
    *,
    agent: str,
    now: datetime,
) -> None:
    """Carry one share out in Meko, then link it."""
    if item.target == "fact":
        await _share_preference(engine, meko, household_id, conversation_id, item, agent, now)
    else:
        await _share_decision(engine, meko, household_id, conversation_id, item, agent, now)


async def _household_name(conn: AsyncConnection, household_id: uuid.UUID) -> tuple[str, str]:
    row = (
        await conn.execute(
            select(HOUSEHOLD.c.name, HOUSEHOLD.c.timezone).where(HOUSEHOLD.c.id == household_id)
        )
    ).one()
    return row.name, row.timezone


async def preference_sentence(
    conn: AsyncConnection, household_id: uuid.UUID, fact_id: uuid.UUID
) -> str:
    """The words a preference is shared in: its sentence while in force."""
    name, _ = await _household_name(conn, household_id)
    fact = next(f for f in await load_facts(conn, household_id) if f.id == fact_id)
    entities = {e.id: e for e in await load_entities(conn, household_id)}
    entity = entities.get(fact.entity_id) if fact.entity_id is not None else None
    sentence = fact_sentence(fact, name, entity)
    if sentence is None:
        raise MekoError(f"fact {fact_id} was retracted: it isn't shared")
    return sentence


async def _share_preference(
    engine: AsyncEngine,
    meko: Meko,
    household_id: uuid.UUID,
    conversation_id: str,
    item: Share,
    agent: str,
    now: datetime,
) -> None:
    async with engine.connect() as conn:
        sentence = await preference_sentence(conn, household_id, item.row_id)
    promoted = await meko.promoted_memories(conversation_id, agent_id=agent)
    memory_id = next(
        (m.id for m in promoted.memories if m.text == sentence and m.agent_id == agent), None
    )
    if memory_id is None:
        memory_id = await meko.add_memory(
            conversation_id,
            sentence,
            {"kako_source": "promotion", "fact_id": str(item.row_id)},
            agent_id=agent,
        )
        try:
            done = await meko.promote_memories(conversation_id, [memory_id], agent_id=agent)
            if memory_id not in done:
                raise MekoError(f"Meko didn't promote memory {memory_id}")
        except MekoError:
            # An unpromoted copy would be found as an ordinary memory: take it back, if Meko lets.
            with contextlib.suppress(MekoError):
                await meko.delete_memory(conversation_id, memory_id, agent_id=agent)
            raise
    await _link(engine, "fact", item.row_id, "promoted_memory", memory_id, agent, sentence, now)


async def decision_record_for(
    conn: AsyncConnection, household_id: uuid.UUID, decision_id: uuid.UUID
) -> tuple[str, str]:
    """The decision record's file name and Markdown, from the household's rows."""
    name, timezone = await _household_name(conn, household_id)
    made = PROPOSAL.alias("made")
    row = (
        await conn.execute(
            select(DECISION, SESSION.c.title, made.c.decided_at, PERSON.c.display_name)
            .join(SESSION, SESSION.c.id == DECISION.c.session_id)
            .join(made, made.c.id == DECISION.c.proposal_id)
            .join(PERSON, PERSON.c.id == made.c.decided_by_person_id)
            .where(DECISION.c.id == decision_id, DECISION.c.household_id == household_id)
        )
    ).one()
    options = list(
        await conn.execute(
            select(OPTION).where(OPTION.c.decision_id == decision_id).order_by(OPTION.c.label)
        )
    )
    rests_on = set(
        (
            await conn.execute(
                select(ASSUMPTION.c.fact_id).where(ASSUMPTION.c.decision_id == decision_id)
            )
        ).scalars()
    )
    facts = tuple(f for f in await load_facts(conn, household_id) if f.id in rests_on)
    entities = {e.id: e for e in await load_entities(conn, household_id)}
    earlier = DECISION.alias("earlier")
    chosen_then = OPTION.alias("chosen_then")
    revised = (
        await conn.execute(
            select(earlier.c.question, chosen_then.c.label, SESSION.c.title)
            .join(chosen_then, chosen_then.c.id == earlier.c.chosen_option_id)
            .join(SESSION, SESSION.c.id == earlier.c.session_id)
            .where(earlier.c.replaced_by == decision_id)
        )
    ).first()
    chosen = next((o.label for o in options if o.id == row.chosen_option_id), "?")
    record = DecisionRecord(
        id=row.id,
        question=row.question,
        chosen=chosen,
        reasoning=row.reasoning,
        valid_from=row.valid_from,
        session_title=row.title,
        approved_by=row.display_name,
        approved_on=row.decided_at.astimezone(ZoneInfo(timezone)).date(),
        options=tuple(
            OptionRecord(o.label, o.id == row.chosen_option_id, o.rejected_reason) for o in options
        ),
        rests_on=facts,
        revises=Revised(*revised) if revised is not None else None,
    )
    return record_filename(record), decision_record(name, record, entities)


async def _share_decision(
    engine: AsyncEngine,
    meko: Meko,
    household_id: uuid.UUID,
    conversation_id: str,
    item: Share,
    agent: str,
    now: datetime,
) -> None:
    async with engine.connect() as conn:
        filename, text = await decision_record_for(conn, household_id, item.row_id)
    document = await meko.upload_document(
        conversation_id, filename, text.encode("utf-8"), agent_id=agent
    )
    await _link(engine, "decision", item.row_id, "document", document.key, agent, None, now)


async def _link(
    engine: AsyncEngine,
    table: str,
    row_id: uuid.UUID,
    kind: str,
    meko_id: str,
    agent: str,
    text: str | None,
    now: datetime,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            MEKO_LINK.insert().values(
                kako_table=table,
                kako_id=row_id,
                meko_kind=kind,
                meko_id=meko_id,
                created_at=now,
                agent_id=agent,
                text=text,
            )
        )
