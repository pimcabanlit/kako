"""V-13, the link check: each `meko_link` to a memory points to a memory Meko holds.

`check_links` reads Meko once a memory, plus one call for upkeep's conversation, and changes
nothing. It also reports the upkeep still owed (a fact with no memory yet, a sentence not yet
rewritten in the past tense, a memory not yet deleted), so after `kako meko sync` it is empty.
`kako meko check` runs it and exits 1 on any problem.
"""

from __future__ import annotations

import uuid
from typing import Any, Final, cast

from sqlalchemy import Table, and_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.db.models import Fact, Household, LifeEvent, MekoLink
from kako.meko.adapter import Meko
from kako.upkeep.sync import AGENT, plan_for, session_key

HOUSEHOLD = cast(Table, Household.__table__)
FACT = cast(Table, Fact.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
LINKED: Final = {"fact": FACT, "life_event": LIFE_EVENT}  # the household's rows a memory can tie


def check_calls(links: int) -> int:
    """The Meko calls a check of this many links makes."""
    return 1 + links


async def memory_links(engine: AsyncEngine, household_id: uuid.UUID) -> list[Any]:
    """Every link from one of the household's facts or life events to a memory."""
    found: list[Any] = []
    async with engine.connect() as conn:
        for name, table in LINKED.items():
            rows = await conn.execute(
                select(
                    MEKO_LINK.c.kako_table,
                    MEKO_LINK.c.kako_id,
                    MEKO_LINK.c.meko_id,
                    MEKO_LINK.c.text,
                )
                .join(
                    table,
                    and_(MEKO_LINK.c.kako_table == name, table.c.id == MEKO_LINK.c.kako_id),
                )
                .where(table.c.household_id == household_id, MEKO_LINK.c.meko_kind == "memory")
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
    name = household.name
    if household.meko_datapack_id is not None and meko.datapack_id != household.meko_datapack_id:
        return [*problems, "Meko isn't on this household's datapack: nothing to compare"]
    for step in owed:
        problems.append(
            f"fact {step.fact.id} ({step.fact.attribute}): upkeep owes a {step.kind} "
            "(kako meko sync)"
        )
    links = await memory_links(engine, household_id)
    if not links:
        return problems
    conversation_id = await meko.create_conversation(
        agent_id=AGENT, title=f"Kako's memory of the {name}", session_key=session_key(household_id)
    )
    held: dict[str, Any] = {}
    for link in links:
        if link.meko_id not in held:
            held[link.meko_id] = await meko.get_memory(
                conversation_id, link.meko_id, agent_id=AGENT
            )
        memory = held[link.meko_id]
        if memory is None:
            problems.append(
                f"{link.kako_table} {link.kako_id}: memory {link.meko_id} isn't in Meko (V-13)"
            )
        elif link.text is not None and memory.text != link.text:
            problems.append(
                f"{link.kako_table} {link.kako_id}: memory {link.meko_id} doesn't say what Kako "
                "wrote"
            )
    return problems
