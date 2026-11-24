"""Carrying out each candidate's fate: Meko's extracted memories end linked or deleted (V-14).

A dreaming run keeps each memory Meko extracted from the session in its counts (`memories`), with
the fate `candidates.py` gave it. `settle_memories` carries the fates out, as often as it is run:

- **waiting**: once a person has approved every one of its proposals, each of which showed the
  memory's words as `extracted_memory` evidence, `meko_link` ties it to the facts and life events
  they wrote (**linked**), and the brief marks it approved. Once any of them is rejected or expired,
  or what was approved writes nothing (a retraction), it is to be deleted. While any is pending, it
  waits.
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
from kako.db.models import (
    DreamRun,
    Fact,
    LifeEvent,
    MekoLink,
    Proposal,
    ProposalEvidence,
    Session,
)
from kako.dreaming.candidates import MAX_NOTED
from kako.dreaming.extract import said_turns
from kako.dreaming.job import people, read_session, session_noted, session_turns
from kako.health import safe_error
from kako.meko.adapter import AGENT_ID, Meko
from kako.meko.client import MekoCallLimitError, MekoError, MekoToolError, is_not_found
from kako.meko.quota import MekoQuotaError

DREAM_RUN = cast(Table, DreamRun.__table__)
SESSION = cast(Table, Session.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
FACT = cast(Table, Fact.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
EVIDENCE = cast(Table, ProposalEvidence.__table__)
OPEN: Final = frozenset({"waiting", "delete"})  # states settling still has to carry out
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


async def _link(
    conn: AsyncConnection,
    rows: Sequence[tuple[str, uuid.UUID]],
    memory_id: str,
    agent_id: str | None,
    at: datetime,
) -> None:
    """Tie the memory, in Meko's own words (no `text`), to what was written, naming its writer."""
    for table, row_id in rows:
        await conn.execute(
            insert(MEKO_LINK)
            .values(
                kako_table=table,
                kako_id=row_id,
                meko_kind="memory",
                meko_id=memory_id,
                created_at=at,
                agent_id=agent_id,
            )
            .on_conflict_do_nothing()
        )


async def _link_or_wait(
    engine: AsyncEngine, run: _Run, entry: dict[str, Any], at: datetime
) -> None:
    """Move a waiting entry on, in one transaction: still waiting, linked or to delete. It is linked
    only when a person approved every proposal it waits on, each of which showed its words."""
    memory_id = str(entry["memory_id"])
    ids = _ids(entry.get("proposal_ids"))
    async with engine.begin() as conn:
        statuses: dict[uuid.UUID, str] = {}
        if ids:
            rows = await conn.execute(
                select(PROPOSAL.c.id, PROPOSAL.c.status).where(
                    PROPOSAL.c.id.in_(ids), PROPOSAL.c.household_id == run.household_id
                )
            )
            statuses = {r.id: r.status for r in rows}
        if not ids or len(statuses) != len(set(ids)):
            entry.update(state="delete", reason="what it waits on isn't this household's")
            return
        if any(s in ("rejected", "expired") for s in statuses.values()):
            entry.update(state="delete", reason="the household didn't approve it")
            return
        if "pending" in statuses.values():
            return
        shown = {
            r.proposal_id
            for r in await conn.execute(
                select(EVIDENCE.c.proposal_id).where(
                    EVIDENCE.c.proposal_id.in_(ids),
                    EVIDENCE.c.kind == "extracted_memory",
                    EVIDENCE.c.ref == memory_id,
                )
            )
        }
        if shown != set(ids):
            entry.update(state="delete", reason="a person approved it without seeing its words")
            return
        written = await _written(conn, run.household_id, ids)
        if not written:
            entry.update(state="delete", reason="what the household approved writes no fact")
            return
        agent = entry.get("agent_id")
        await _link(conn, written, memory_id, agent if isinstance(agent, str) else None, at)
        entry.update(state="linked", links=[[t, str(i)] for t, i in written])


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
        if not is_not_found(exc):
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
            if entry.get("state") == "waiting":
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


async def forgotten(
    engine: AsyncEngine, household_id: uuid.UUID, memory_id: str, reason: str
) -> None:
    """A linked memory Meko extracted, deleted by Meko upkeep once the fact it was linked to was
    replaced or retracted: its entry says so, and V-14 then checks it is gone."""
    async with engine.begin() as conn:
        rows = await conn.execute(
            select(DREAM_RUN.c.id, DREAM_RUN.c.counts)
            .join(SESSION, SESSION.c.id == DREAM_RUN.c.session_id)
            .where(DREAM_RUN.c.status == "done", SESSION.c.household_id == household_id)
            .with_for_update(of=DREAM_RUN)
        )
        for run_id, counts in list(rows):
            counts = dict(counts or {})
            entries = [dict(e) for e in counts.get("memories") or () if isinstance(e, dict)]
            hit = False
            for e in entries:
                if str(e.get("memory_id")) == memory_id and e.get("state") == "linked":
                    e.update(state="deleted", reason=reason)
                    hit = True
            if hit:
                await conn.execute(
                    update(DREAM_RUN)
                    .where(DREAM_RUN.c.id == run_id)
                    .values(counts={**counts, "memories": entries})
                )


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
