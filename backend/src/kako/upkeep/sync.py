"""Meko upkeep: carry the plan out (`plan.py`), as often as it is run.

`keep_up` reads the household's facts and their links, then, one step at a time, adds Kako's own
memory of a fact (as `kako:upkeep`, in a conversation of its own), rewrites one whose sentence
changed (a replaced fact in the past tense), and deletes a memory linked to a retracted fact, or one
in Meko's words linked to a replaced fact. Each step is a Meko call, then its link written or
removed in its own transaction, so a run that stops leaves only finished steps behind and the next
run picks up the rest. A memory is changed or deleted as the agent that wrote it, the only one Meko
allows; one Meko no longer holds counts as gone. At most `max_steps` steps a run, and none at all
while another run holds the household (a Postgres advisory lock), so two runs can't both add a
fact's memory.

It runs after every approval (the approvals API and `kako proposals approve`), in `kako demo run`,
and with `kako meko sync`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import Table, and_, delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.db.fact_store import load_entities, load_facts
from kako.db.models import Fact, Household, MekoLink
from kako.dreaming.memories import forgotten
from kako.health import safe_error
from kako.meko.adapter import AGENT_ID, Meko
from kako.meko.client import MekoCallLimitError, MekoError, MekoToolError, is_not_found
from kako.meko.quota import MekoQuotaError
from kako.settings import Settings
from kako.upkeep.plan import Link, Step, plan_upkeep

HOUSEHOLD = cast(Table, Household.__table__)
FACT = cast(Table, Fact.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
AGENT: Final = "kako:upkeep"
MAX_STEPS: Final = 60  # Meko calls one run makes for its steps, besides its conversation
LOCK: Final = 0x4B414B4F  # "KAKO": the advisory lock's first key; the household's is the second


class UpkeepError(Exception):
    """Upkeep can't run here, such as on another household's datapack."""


@dataclass
class UpkeepReport:
    added: int = 0
    rewritten: int = 0
    deleted: int = 0
    waiting: int = 0  # steps left for the next run
    busy: bool = False  # another run held the household
    problems: list[str] = field(default_factory=list)

    @property
    def steps(self) -> int:
        return self.added + self.rewritten + self.deleted


def session_key(household_id: uuid.UUID) -> str:
    """Upkeep's own conversation: the same key reconnects it, so a run costs one
    `conversation_create`."""
    return f"kako-upkeep-{household_id}"


async def fact_links(conn: AsyncConnection, household_id: uuid.UUID) -> list[Link]:
    """Every link from one of the household's facts to a memory."""
    rows = await conn.execute(
        select(MEKO_LINK.c.kako_id, MEKO_LINK.c.meko_id, MEKO_LINK.c.agent_id, MEKO_LINK.c.text)
        .join(FACT, and_(MEKO_LINK.c.kako_table == "fact", FACT.c.id == MEKO_LINK.c.kako_id))
        .where(FACT.c.household_id == household_id, MEKO_LINK.c.meko_kind == "memory")
    )
    return [Link(r.kako_id, r.meko_id, r.agent_id, r.text) for r in rows]


async def _household(conn: AsyncConnection, household_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            select(HOUSEHOLD.c.name, HOUSEHOLD.c.meko_datapack_id).where(
                HOUSEHOLD.c.id == household_id
            )
        )
    ).first()
    if row is None:
        raise UpkeepError("no such household")
    return row


async def plan_for(conn: AsyncConnection, household_id: uuid.UUID) -> list[Step]:
    """What upkeep owes Meko for the household now."""
    household = await _household(conn, household_id)
    entities = {e.id: e for e in await load_entities(conn, household_id)}
    facts = await load_facts(conn, household_id)
    return plan_upkeep(facts, await fact_links(conn, household_id), household.name, entities)


def metadata(fact_id: uuid.UUID, attribute: str, valid_from: str) -> dict[str, Any]:
    """Kako's own memory of a fact. A `kako_` key marks it as Kako's, never a candidate for
    dreaming; Meko keeps the metadata on update but can't change it."""
    return {
        "kako_source": "fact",
        "fact_id": str(fact_id),
        "attribute": attribute,
        "valid_from": valid_from,
    }


async def keep_up(
    engine: AsyncEngine,
    meko: Meko,
    household_id: uuid.UUID,
    *,
    now: datetime,
    max_steps: int = MAX_STEPS,
) -> UpkeepReport:
    """Bring Meko in line with the household's facts, at most `max_steps` steps this run."""
    report = UpkeepReport()
    async with engine.connect() as lock:
        key = int.from_bytes(household_id.bytes[:4], "big", signed=True)
        held = (
            await lock.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), {"a": LOCK, "b": key})
        ).scalar_one()
        await lock.commit()
        if not held:
            report.busy = True
            return report
        try:
            await _run(engine, meko, household_id, now, max_steps, report)
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(:a, :b)"), {"a": LOCK, "b": key})
            await lock.commit()
    return report


async def _run(
    engine: AsyncEngine,
    meko: Meko,
    household_id: uuid.UUID,
    now: datetime,
    max_steps: int,
    report: UpkeepReport,
) -> None:
    async with engine.connect() as conn:
        household = await _household(conn, household_id)
        steps = await plan_for(conn, household_id)
    if not steps:
        return
    if household.meko_datapack_id is not None and meko.datapack_id != household.meko_datapack_id:
        raise UpkeepError("Meko isn't on this household's datapack")
    try:
        conversation_id = await meko.create_conversation(
            agent_id=AGENT,
            title=f"Kako's memory of the {household.name}",
            session_key=session_key(household_id),
        )
    except (MekoQuotaError, MekoCallLimitError):
        report.waiting = len(steps)
        return
    for n, step in enumerate(steps):
        if n >= max_steps:
            report.waiting = len(steps) - n
            return
        try:
            await _step(engine, meko, household_id, conversation_id, step, now, report)
        except (MekoQuotaError, MekoCallLimitError):
            report.waiting = len(steps) - n
            return
        except MekoError as exc:
            report.problems.append(f"fact {step.fact.id}: {step.kind}: {safe_error(exc)}")


async def _step(
    engine: AsyncEngine,
    meko: Meko,
    household_id: uuid.UUID,
    conversation_id: str,
    step: Step,
    now: datetime,
    report: UpkeepReport,
) -> None:
    fact = step.fact
    if step.kind == "add":
        if step.text is None:
            raise UpkeepError("an add step without its sentence")
        memory_id = await meko.add_memory(
            conversation_id,
            step.text,
            metadata(fact.id, fact.attribute, fact.valid_from.isoformat()),
            agent_id=AGENT,
        )
        async with engine.begin() as conn:
            await conn.execute(
                MEKO_LINK.insert().values(
                    kako_table="fact",
                    kako_id=fact.id,
                    meko_kind="memory",
                    meko_id=memory_id,
                    created_at=now,
                    agent_id=AGENT,
                    text=step.text,
                )
            )
        report.added += 1
        return
    link = step.link
    if link is None:
        raise UpkeepError(f"a {step.kind} step without its memory")
    agent = link.agent_id or AGENT
    if not AGENT_ID.fullmatch(agent):
        report.problems.append(
            f"memory {link.memory_id}: written by {agent}: only that agent can change it"
        )
        return
    if step.kind == "rewrite":
        if step.text is None:
            raise UpkeepError("a rewrite step without its sentence")
        try:
            await meko.update_memory(conversation_id, link.memory_id, step.text, agent_id=agent)
        except MekoToolError as exc:
            if not is_not_found(exc):
                raise
            await _unlink(engine, link)  # gone from Meko: the next run adds it again
            report.problems.append(
                f"memory {link.memory_id} was gone from Meko: added again next run"
            )
            return
        async with engine.begin() as conn:
            await conn.execute(update(MEKO_LINK).where(*_is(link)).values(text=step.text))
        report.rewritten += 1
        return
    try:
        await meko.delete_memory(conversation_id, link.memory_id, agent_id=agent)
    except MekoToolError as exc:
        if not is_not_found(exc):
            raise
    await _unlink(engine, link)
    if not link.own:
        why = (
            "its fact was retracted: the household said it was wrong"
            if fact.status == "retracted"
            else "its fact was replaced: Kako's own memory keeps it in the past tense"
        )
        await forgotten(engine, household_id, link.memory_id, why)
    report.deleted += 1


def _is(link: Link) -> tuple[Any, ...]:
    return (
        MEKO_LINK.c.kako_table == "fact",
        MEKO_LINK.c.kako_id == link.fact_id,
        MEKO_LINK.c.meko_kind == "memory",
        MEKO_LINK.c.meko_id == link.memory_id,
    )


async def _unlink(engine: AsyncEngine, link: Link) -> None:
    """The memory is gone: every link to it goes (one in Meko's words can tie a life event and
    its facts together), so V-13 holds."""
    async with engine.begin() as conn:
        await conn.execute(
            delete(MEKO_LINK).where(
                MEKO_LINK.c.meko_kind == "memory", MEKO_LINK.c.meko_id == link.memory_id
            )
        )


async def keep_up_with(
    engine: AsyncEngine, settings: Settings, household_id: uuid.UUID, *, now: datetime
) -> UpkeepReport:
    """`keep_up` on the configured Meko, every call counted in `meko_call`."""
    from kako.db.meko_log import DbCallLog
    from kako.meko.mcp import open_meko

    async with open_meko(settings, DbCallLog(engine), max_calls=1 + MAX_STEPS) as meko:
        return await keep_up(engine, meko, household_id, now=now)
