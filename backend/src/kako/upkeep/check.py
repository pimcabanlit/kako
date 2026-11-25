"""V-13, the link check: each `meko_link` to a memory, a promoted memory or a document points to
one Meko holds.

`check_links` reads Meko once a memory or document, once for the promoted memories, plus one call
for upkeep's conversation, and changes nothing. A promoted memory is looked for among those Meko
lists (its newest 20): one beyond them can't be checked, and isn't reported. It also reports the
upkeep still owed (a fact with no memory yet, a sentence not yet rewritten in the past tense, a
memory not yet deleted, an approved promotion not yet shared, an ended session's recap not yet
added), so after `kako meko sync` it is empty. `kako meko check` runs it and exits 1 on any problem.
"""

from __future__ import annotations

import uuid
from typing import Any, Final, cast

from sqlalchemy import Table, and_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.db.models import Decision, Fact, Household, LifeEvent, MekoLink, Session
from kako.meko.adapter import Meko, Promoted
from kako.meko.client import MekoToolError, is_not_found
from kako.upkeep.promote import shares_owed
from kako.upkeep.recaps import recaps_owed
from kako.upkeep.sync import AGENT, plan_for, session_key

HOUSEHOLD = cast(Table, Household.__table__)
FACT = cast(Table, Fact.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
DECISION = cast(Table, Decision.__table__)
SESSION = cast(Table, Session.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
# The household's rows a link can tie to what Meko holds.
LINKED: Final = {
    "fact": FACT,
    "life_event": LIFE_EVENT,
    "decision": DECISION,
    "session": SESSION,
}
CHECKED: Final = ("memory", "promoted_memory", "document")


def check_calls(links: int) -> int:
    """The Meko calls a check of this many links makes, at most."""
    return 2 + links


async def memory_links(engine: AsyncEngine, household_id: uuid.UUID) -> list[Any]:
    """Every link from one of the household's rows to a memory, a promoted memory or a
    document."""
    found: list[Any] = []
    async with engine.connect() as conn:
        for name, table in LINKED.items():
            rows = await conn.execute(
                select(
                    MEKO_LINK.c.kako_table,
                    MEKO_LINK.c.kako_id,
                    MEKO_LINK.c.meko_kind,
                    MEKO_LINK.c.meko_id,
                    MEKO_LINK.c.text,
                )
                .join(
                    table,
                    and_(MEKO_LINK.c.kako_table == name, table.c.id == MEKO_LINK.c.kako_id),
                )
                .where(table.c.household_id == household_id, MEKO_LINK.c.meko_kind.in_(CHECKED))
                .order_by(MEKO_LINK.c.meko_id)
            )
            found += list(rows)
    return found


async def check_links(engine: AsyncEngine, meko: Meko, household_id: uuid.UUID) -> list[str]:
    """What is wrong between the household's rows and Meko (empty: V-13 holds, nothing owed)."""
    problems: list[str] = []
    async with engine.connect() as conn:
        household = (
            await conn.execute(
                select(HOUSEHOLD.c.name, HOUSEHOLD.c.meko_datapack_id).where(
                    HOUSEHOLD.c.id == household_id
                )
            )
        ).one()
        owed = await plan_for(conn, household_id)
        unshared = await shares_owed(conn, household_id)
        unrecapped = await recaps_owed(conn, household_id)
    name = household.name
    if household.meko_datapack_id is not None and meko.datapack_id != household.meko_datapack_id:
        return [*problems, "Meko isn't on this household's datapack: nothing to compare"]
    for step in owed:
        problems.append(
            f"fact {step.fact.id} ({step.fact.attribute}): upkeep owes a {step.kind} "
            "(kako meko sync)"
        )
    for item in unshared:
        problems.append(
            f"{item.target} {item.row_id}: approved for sharing, not shared yet (kako meko sync)"
        )
    for recap in unrecapped:
        problems.append(
            f"session {recap.session_id}: ended, its recap not in Meko yet (kako meko sync)"
        )
    links = await memory_links(engine, household_id)
    if not links:
        return problems
    conversation_id = await meko.create_conversation(
        agent_id=AGENT, title=f"Kako's memory of the {name}", session_key=session_key(household_id)
    )
    held: dict[str, Any] = {}
    promoted: Promoted | None = None
    for link in links:
        where = f"{link.kako_table} {link.kako_id}"
        if link.meko_kind == "document":
            problem = await _document_problem(meko, conversation_id, link.meko_id)
            if problem is not None:
                problems.append(f"{where}: {problem}")
            continue
        if link.meko_kind == "promoted_memory":
            if promoted is None:
                promoted = await meko.promoted_memories(conversation_id, agent_id=AGENT)
            found = next((m for m in promoted.memories if m.id == link.meko_id), None)
            if found is None and promoted.complete:
                problems.append(
                    f"{where}: memory {link.meko_id} isn't in Meko's collective memory (V-13)"
                )
            elif found is not None and link.text is not None and found.text != link.text:
                problems.append(
                    f"{where}: promoted memory {link.meko_id} doesn't say what Kako shared"
                )
            continue
        if link.meko_id not in held:
            held[link.meko_id] = await meko.get_memory(
                conversation_id, link.meko_id, agent_id=AGENT
            )
        memory = held[link.meko_id]
        if memory is None:
            problems.append(f"{where}: memory {link.meko_id} isn't in Meko (V-13)")
        elif link.text is not None and memory.text != link.text:
            problems.append(f"{where}: memory {link.meko_id} doesn't say what Kako wrote")
    return problems


async def _document_problem(meko: Meko, conversation_id: str, key: str) -> str | None:
    try:
        document = await meko.document_status(conversation_id, key, agent_id=AGENT)
    except MekoToolError as exc:
        if not is_not_found(exc):
            raise
        return f"document {key} isn't in Meko's knowledge base (V-13)"
    if document.state == "failed":
        return f"document {key} failed to index: {document.message or 'Meko gave no reason'}"
    if document.state == "awaiting_upload":
        return f"document {key} was never uploaded (V-13)"
    return None
