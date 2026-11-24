"""Carrying out each candidate's fate: Meko's extracted memories end linked or deleted (V-14).

A dreaming run keeps each memory Meko extracted from the session in its counts (`memories`), with
the fate `candidates.py` gave it. `settle_memories` carries the fates out, as often as it is run:

- **waiting**: once a person approves one of its proposals, `meko_link` ties the memory to the fact
  or life event that proposal wrote (**linked**); once none of them is pending or approved (the
  household said no, or the proposal expired), or what was approved writes nothing (a retraction),
  it is to be deleted. Still pending: it waits.
- **link**: `meko_link` ties it to the fact or life event Kako holds (**linked**); if that row is
  gone, it is to be deleted.
- **delete**: deleted in Meko as the agent that wrote it, the only one Meko lets delete it
  (**deleted**). One gone already counts as deleted. One written by an agent that isn't Kako's
  can't be: it is **undeletable**, and the V-14 check says so.

`check_extracted` is the V-14 check: every memory Meko holds from a session dreaming has run on is
linked, or waits on a pending proposal; nothing it deleted is still there; and nothing Meko
extracted was missed. It reads Meko (two calls a run) and Postgres, and changes nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import Table, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.agents.ask import LOCAL_PREFIX
from kako.db.models import DreamRun, Fact, LifeEvent, MekoLink, Proposal, Session
from kako.dreaming.candidates import MAX_NOTED
from kako.dreaming.extract import said_turns
from kako.dreaming.job import people, read_session, session_noted, session_turns
from kako.health import safe_error
from kako.meko.adapter import AGENT_ID, Meko
from kako.meko.client import MekoCallLimitError, MekoError, MekoToolError
from kako.meko.quota import MekoQuotaError

DREAM_RUN = cast(Table, DreamRun.__table__)
SESSION = cast(Table, Session.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
FACT = cast(Table, Fact.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
OPEN: Final = frozenset({"waiting", "link", "delete"})  # states settling still has to carry out
WRITTEN: Final = {"fact": FACT, "life_event": LIFE_EVENT}
CHECK_RUNS: Final = 100  # dreamed sessions one check reads
CHECK_CALLS: Final = 2 * CHECK_RUNS  # each: its turns and its memories


@dataclass
class SettleReport:
    linked: int = 0
    deleted: int = 0
    waiting: int = 0  # on a pending proposal, or a delete left for the next run
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Run:
    id: uuid.UUID
    session_id: uuid.UUID
    household_id: uuid.UUID
    conversation_id: str
    counts: dict[str, Any]

    @property
    def entries(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self.counts.get("memories") or () if isinstance(e, dict)]


async def _runs(
    conn: AsyncConnection, *, run_id: uuid.UUID | None, household_id: uuid.UUID | None
) -> list[_Run]:
    query = (
        select(
            DREAM_RUN.c.id,
            DREAM_RUN.c.session_id,
            DREAM_RUN.c.counts,
            SESSION.c.household_id,
            SESSION.c.meko_conversation_id,
        )
        .join(SESSION, SESSION.c.id == DREAM_RUN.c.session_id)
        .where(DREAM_RUN.c.status == "done")
        .order_by(SESSION.c.ended_at, DREAM_RUN.c.id)
    )
    if run_id is not None:
        query = query.where(DREAM_RUN.c.id == run_id)
    if household_id is not None:
        query = query.where(SESSION.c.household_id == household_id)
    return [
        _Run(r.id, r.session_id, r.household_id, r.meko_conversation_id, dict(r.counts or {}))
        for r in await conn.execute(query)
    ]


def _ids(values: Any) -> list[uuid.UUID]:
    out = []
    for v in values or ():
        try:
            out.append(uuid.UUID(str(v)))
        except ValueError:
            continue
    return out


async def _written(
    conn: AsyncConnection, household_id: uuid.UUID, proposal_ids: Sequence[uuid.UUID]
) -> list[tuple[str, uuid.UUID]]:
    """The facts and life events these proposals wrote, in this household."""
    found: list[tuple[str, uuid.UUID]] = []
    for name, table in WRITTEN.items():
        rows = await conn.execute(
            select(table.c.id).where(
                table.c.proposal_id.in_(list(proposal_ids)), table.c.household_id == household_id
            )
        )
        found += [(name, r.id) for r in rows]
    return found


async def _held(
    conn: AsyncConnection, household_id: uuid.UUID, held: Sequence[Any]
) -> list[tuple[str, uuid.UUID]]:
    """Of the rows a `link` candidate names, those this household holds (a fact not retracted)."""
    found: list[tuple[str, uuid.UUID]] = []
    for item in held:
        if not isinstance(item, list | tuple) or len(item) != 2 or item[0] not in WRITTEN:
            continue
        (row_id,) = _ids([item[1]]) or (None,)
        if row_id is None:
            continue
        table = WRITTEN[item[0]]
        query = select(table.c.id).where(table.c.id == row_id, table.c.household_id == household_id)
        if item[0] == "fact":
            query = query.where(table.c.status != "retracted")
        if (await conn.execute(query)).first() is not None:
            found.append((item[0], row_id))
    return found


async def _link(
    conn: AsyncConnection, rows: Sequence[tuple[str, uuid.UUID]], memory_id: str, at: datetime
) -> None:
    for table, row_id in rows:
        await conn.execute(
            insert(MEKO_LINK)
            .values(
                kako_table=table,
                kako_id=row_id,
                meko_kind="memory",
                meko_id=memory_id,
                created_at=at,
            )
            .on_conflict_do_nothing()
        )


async def _link_or_wait(
    engine: AsyncEngine, run: _Run, entry: dict[str, Any], at: datetime
) -> None:
    """Move a waiting or link entry on, in one transaction: linked, still waiting, or delete."""
    async with engine.begin() as conn:
        if entry["state"] == "link":
            rows = await _held(conn, run.household_id, entry.get("held") or ())
            if not rows:
                entry.update(state="delete", reason="what it was the same as is gone")
                return
        else:
            ids = _ids(entry.get("proposal_ids"))
            statuses = (
                {
                    r.id: r.status
                    for r in await conn.execute(
                        select(PROPOSAL.c.id, PROPOSAL.c.status).where(
                            PROPOSAL.c.id.in_(ids), PROPOSAL.c.household_id == run.household_id
                        )
                    )
                }
                if ids
                else {}
            )
            approved = [i for i, s in statuses.items() if s == "approved"]
            rows = await _written(conn, run.household_id, approved) if approved else []
            if not rows:
                if "pending" in statuses.values():
                    return
                why = (
                    "what the household approved writes no fact"
                    if approved
                    else "the household didn't approve it"
                )
                entry.update(state="delete", reason=why)
                return
        await _link(conn, rows, str(entry["memory_id"]), at)
        entry.update(state="linked", links=[[t, str(i)] for t, i in rows])


async def _delete(meko: Meko, run: _Run, entry: dict[str, Any], report: SettleReport) -> bool:
    """Delete one memory in Meko as the agent that wrote it; False when Meko refused any more
    calls (the rest wait for the next run)."""
    agent = entry.get("agent_id")
    memory_id = str(entry["memory_id"])
    if not isinstance(agent, str) or not AGENT_ID.fullmatch(agent):
        entry.update(
            state="undeletable",
            reason=f"written by {agent or 'an unnamed agent'}: only that agent can delete it",
        )
        report.problems.append(f"memory {memory_id}: {entry['reason']}")
        return True
    try:
        await meko.delete_memory(run.conversation_id, memory_id, agent_id=agent)
    except (MekoQuotaError, MekoCallLimitError):
        report.waiting += 1
        return False
    except MekoToolError as exc:
        text = str(exc).lower()
        if "not found" not in text and "not_found" not in text:
            entry["error"] = safe_error(exc)
            report.problems.append(f"memory {memory_id}: {entry['error']}")
            return True
    except MekoError as exc:
        entry["error"] = safe_error(exc)
        report.problems.append(f"memory {memory_id}: {entry['error']}")
        return True
    entry.pop("error", None)
    entry["state"] = "deleted"
    report.deleted += 1
    return True


async def settle_memories(
    engine: AsyncEngine,
    meko: Meko,
    *,
    now: datetime,
    run_id: uuid.UUID | None = None,
    max_deletes: int = MAX_NOTED,
) -> SettleReport:
    """Carry out the fates of the candidates of every done run (or one), deleting at most
    `max_deletes` memories in Meko; what is left waits for the next call."""
    report = SettleReport()
    async with engine.connect() as conn:
        runs = await _runs(conn, run_id=run_id, household_id=None)
    deletes = max_deletes
    for run in runs:
        entries = run.entries
        if not any(e.get("state") in OPEN for e in entries):
            continue
        for entry in entries:
            if entry.get("state") in ("waiting", "link"):
                await _link_or_wait(engine, run, entry, now)
                if entry["state"] == "linked":
                    report.linked += 1
                elif entry["state"] == "waiting":
                    report.waiting += 1
            if entry.get("state") == "delete":
                if deletes <= 0 or run.conversation_id.startswith(LOCAL_PREFIX):
                    report.waiting += 1
                    continue
                deletes -= 1
                if not await _delete(meko, run, entry, report):
                    deletes = 0
        async with engine.begin() as conn:
            await conn.execute(
                update(DREAM_RUN)
                .where(DREAM_RUN.c.id == run.id)
                .values(counts={**run.counts, "memories": entries})
            )
    return report


async def check_extracted(
    engine: AsyncEngine, meko: Meko, *, household_id: uuid.UUID | None = None
) -> list[str]:
    """V-14: what is wrong with the memories Meko extracted from sessions dreaming has run on
    (empty: every one is linked, or waits on a pending proposal)."""
    problems: list[str] = []
    async with engine.connect() as conn:
        runs = (await _runs(conn, run_id=None, household_id=household_id))[-CHECK_RUNS:]
    for run in runs:
        entries = {str(e.get("memory_id")): e for e in run.entries}
        async with engine.connect() as conn:
            for memory_id, e in entries.items():
                state = e.get("state")
                if state == "linked":
                    linked = (
                        await conn.execute(
                            select(MEKO_LINK.c.meko_id).where(
                                MEKO_LINK.c.meko_kind == "memory", MEKO_LINK.c.meko_id == memory_id
                            )
                        )
                    ).first()
                    if linked is None:
                        problems.append(f"run {run.id}: memory {memory_id} has no meko_link")
                elif state == "waiting":
                    ids = _ids(e.get("proposal_ids"))
                    pending = (
                        ids
                        and (
                            await conn.execute(
                                select(PROPOSAL.c.id).where(
                                    PROPOSAL.c.id.in_(ids), PROPOSAL.c.status == "pending"
                                )
                            )
                        ).first()
                    )
                    if not pending:
                        problems.append(
                            f"run {run.id}: memory {memory_id} was decided but not settled "
                            "(kako dream settle)"
                        )
                elif state != "deleted":
                    why = e.get("reason") or e.get("error") or "not carried out yet"
                    problems.append(f"run {run.id}: memory {memory_id} is {state}: {why}")
            if run.conversation_id.startswith(LOCAL_PREFIX):
                continue
            session = await read_session(conn, run.session_id)
            names = {p.id: p.display_name for p in await people(conn, run.household_id)}
        turns = said_turns(await session_turns(meko, session, names))
        for n in await session_noted(meko, run.conversation_id, turns):
            kept = entries.get(n.memory_id)
            if kept is None:
                problems.append(
                    f"run {run.id}: memory {n.memory_id} wasn't dreamed over "
                    "(Meko extracted it after the run)"
                )
            elif kept.get("state") == "deleted":
                problems.append(f"run {run.id}: memory {n.memory_id} is still in Meko")
    return problems
