"""A session's turns as the household saw them (`session_turn`), and what the session screen reads.

`keep_turn` writes a turn once it is kept, with who wrote it as a participant of the session, in one
transaction. The reads serve the session screen: the household's sessions, newest first, and one
session's turns, each with the agents' steps the turn logged (`agent_step`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.db.models import (
    AgentStep,
    Person,
    Session,
    SessionParticipant,
    SessionTurn,
    TurnContext,
)

SESSION = cast(Table, Session.__table__)
SESSION_TURN = cast(Table, SessionTurn.__table__)
PARTICIPANT = cast(Table, SessionParticipant.__table__)
AGENT_STEP = cast(Table, AgentStep.__table__)
PERSON = cast(Table, Person.__table__)
TURN_CONTEXT = cast(Table, TurnContext.__table__)


class TurnStoreError(Exception):
    """A turn that can't be kept: its session already has a turn with that seed."""


@dataclass(frozen=True)
class SessionRow:
    id: uuid.UUID
    title: str
    household_date: date
    started_at: datetime
    ended_at: datetime | None
    turns: int
    last_at: datetime  # the last turn's time, or when the session started


@dataclass(frozen=True)
class StepRow:
    seq: int
    agent: str
    tool: str
    input_summary: str
    result_summary: str
    outcome: str
    created_at: datetime


@dataclass(frozen=True)
class TurnRow:
    seed: str
    said_by: uuid.UUID | None
    said_by_name: str | None
    message: str
    shown: dict[str, Any]
    created_at: datetime
    steps: tuple[StepRow, ...]


@dataclass(frozen=True)
class KeptContext:
    """What the turn's agents were given, and the orchestrator's notes for the next turn."""

    brief: str
    brief_tokens: int
    history: dict[str, Any]  # agents.conversation.History.as_json
    search_query: str | None
    topic: str | None
    asks: str | None


async def keep_turn(
    engine: AsyncEngine,
    *,
    session_id: uuid.UUID,
    seed: str,
    said_by: uuid.UUID | None,
    message: str,
    shown: dict[str, Any],
    created_at: datetime,
    context: KeptContext | None = None,
) -> uuid.UUID:
    """Keep the turn as shown, once, with its context (`turn_context`) in the same transaction;
    its writer joins the session's participants."""
    turn_id = uuid.uuid4()
    async with engine.begin() as conn:
        done = await conn.execute(
            insert(SESSION_TURN)
            .values(
                id=turn_id,
                session_id=session_id,
                meko_turn_seed=seed,
                said_by=said_by,
                message=message,
                shown=shown,
                created_at=created_at,
            )
            .on_conflict_do_nothing(index_elements=["session_id", "meko_turn_seed"])
        )
        if done.rowcount != 1:
            raise TurnStoreError(f"session {session_id} already has a turn {seed!r}")
        if context is not None:
            await conn.execute(
                insert(TURN_CONTEXT).values(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    meko_turn_seed=seed,
                    brief=context.brief,
                    brief_tokens=context.brief_tokens,
                    history=context.history,
                    search_query=context.search_query,
                    topic=context.topic,
                    asks=context.asks,
                    created_at=created_at,
                )
            )
        if said_by is not None:
            await conn.execute(
                insert(PARTICIPANT)
                .values(session_id=session_id, person_id=said_by)
                .on_conflict_do_nothing()
            )
    return turn_id


async def list_sessions(conn: AsyncConnection, household_id: uuid.UUID) -> list[SessionRow]:
    """The household's sessions, the most recently active first."""
    turns = (
        select(
            SESSION_TURN.c.session_id,
            func.count().label("turns"),
            func.max(SESSION_TURN.c.created_at).label("last_turn"),
        )
        .group_by(SESSION_TURN.c.session_id)
        .subquery()
    )
    last_at = func.coalesce(turns.c.last_turn, SESSION.c.started_at)
    rows = await conn.execute(
        select(
            SESSION.c.id,
            SESSION.c.title,
            SESSION.c.household_date,
            SESSION.c.started_at,
            SESSION.c.ended_at,
            func.coalesce(turns.c.turns, 0),
            last_at,
        )
        .outerjoin(turns, turns.c.session_id == SESSION.c.id)
        .where(SESSION.c.household_id == household_id)
        .order_by(last_at.desc(), SESSION.c.id)
    )
    return [SessionRow(*row) for row in rows]


async def read_steps(
    conn: AsyncConnection, session_id: uuid.UUID, seeds: Sequence[str]
) -> dict[str, tuple[StepRow, ...]]:
    """The agents' steps of these turns, in the order each turn numbered them."""
    if not seeds:
        return {}
    rows = await conn.execute(
        select(
            AGENT_STEP.c.meko_turn_seed,
            AGENT_STEP.c.seq,
            AGENT_STEP.c.agent,
            AGENT_STEP.c.tool,
            AGENT_STEP.c.input_summary,
            AGENT_STEP.c.result_summary,
            AGENT_STEP.c.outcome,
            AGENT_STEP.c.created_at,
        )
        .where(AGENT_STEP.c.session_id == session_id, AGENT_STEP.c.meko_turn_seed.in_(seeds))
        .order_by(AGENT_STEP.c.meko_turn_seed, AGENT_STEP.c.seq)
    )
    steps: dict[str, list[StepRow]] = {}
    for seed, *rest in rows:
        steps.setdefault(seed, []).append(StepRow(*rest))
    return {seed: tuple(found) for seed, found in steps.items()}


async def read_turns(conn: AsyncConnection, session_id: uuid.UUID) -> list[TurnRow]:
    """The session's kept turns in the order they were taken, each with its steps."""
    rows = (
        await conn.execute(
            select(
                SESSION_TURN.c.meko_turn_seed,
                SESSION_TURN.c.said_by,
                PERSON.c.display_name,
                SESSION_TURN.c.message,
                SESSION_TURN.c.shown,
                SESSION_TURN.c.created_at,
            )
            .outerjoin(PERSON, PERSON.c.id == SESSION_TURN.c.said_by)
            .where(SESSION_TURN.c.session_id == session_id)
            .order_by(SESSION_TURN.c.created_at, SESSION_TURN.c.meko_turn_seed)
        )
    ).all()
    steps = await read_steps(conn, session_id, [row[0] for row in rows])
    return [TurnRow(*row, steps=steps.get(row[0], ())) for row in rows]
