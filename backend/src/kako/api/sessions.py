"""The session API: start a planning session, take a turn in it, read its trace.

- `POST /api/v1/sessions` starts a session: its Meko conversation and its row.
- `POST /api/v1/sessions/{id}/turns` answers the household's message (`agents.ask.run_turn`): the
  options with their figures and sources, any conflict and how it ended, the numbers the check
  flagged, the plan it stored and the turn Meko kept; the changes the household stated, pending
  for a yes (`person_id` names who wrote the message); and in a replan, what changed and why.
- `GET /api/v1/sessions/{id}/trace` is the session's Meko calls as spans: local Meko's call log,
  or Meko Cloud's trace page.

Kako has no sign-in yet: the API serves one household on this machine (`kako api` listens on
127.0.0.1 only). A turn spends model tokens, so turns run one at a time: a second one is refused
while the first runs, on top of the model manager's per-turn budget and daily cap.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Final, Literal, cast

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import (
    LOCAL_PREFIX,
    MEKO_CALLS,
    SessionError,
    Started,
    load_session,
    run_turn,
    start_session,
)
from kako.agents.brief_store import BriefStoreError
from kako.agents.chat import ModelError
from kako.agents.orchestrator import OrchestratorError
from kako.agents.recorded import ChatBackend
from kako.agents.shown import TurnOut, turn_shown
from kako.agents.tools import MESSAGE_CHARS
from kako.db.meko_log import DbCallLog
from kako.db.models import Household, LlmCall, Person, Session
from kako.db.turn_store import StepRow, list_sessions, read_steps, read_turns
from kako.dreaming.job import DREAM_RUN, DreamError, end_session
from kako.health import safe_error
from kako.meko.adapter import Meko
from kako.meko.client import MekoError
from kako.meko.trace import local_trace
from kako.settings import Settings

HOUSEHOLD = cast(Table, Household.__table__)
PERSON = cast(Table, Person.__table__)
SESSION = cast(Table, Session.__table__)
LLM_CALL = cast(Table, LlmCall.__table__)
SEED: Final = re.compile(r"[a-z0-9][a-z0-9:_-]{0,39}")

OpenMeko = Callable[[DbCallLog, int], AbstractAsyncContextManager[Meko | None]]


@dataclass(frozen=True)
class Running:
    """The turn running now: its session and seed, so the screen can show its steps as they come."""

    session_id: uuid.UUID
    seed: str
    message: str
    said_by: uuid.UUID | None
    started_at: datetime


@dataclass
class Services:
    """What the session routes use, built from settings (or by a test)."""

    settings: Settings
    engine: AsyncEngine
    open_meko: OpenMeko
    backend: Callable[[], ChatBackend]
    http: httpx.AsyncClient  # for local Meko's call log
    turn_lock: asyncio.Lock
    running: Running | None = None  # set while a turn runs (one at a time)


router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


def _services(request: Request) -> Services:
    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(503, "KAKO_DATABASE_URL is not set: sessions need the database")
    return services


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewSession(_In):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    household_id: uuid.UUID | None = None  # unset: the only household
    household_date: date | None = None  # unset: the household's own date


class NewTurn(_In):
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MESSAGE_CHARS)
    ]
    known_at: AwareDatetime | None = None
    seed: str | None = Field(default=None, description="The turn's id in the session; t1, t2…")
    person_id: uuid.UUID | None = Field(
        default=None, description="Who wrote the message: a person of the household"
    )


class SessionOut(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    title: str
    household_date: date
    meko_conversation_id: str | None
    trace_url: str | None


class SessionSummaryOut(BaseModel):
    """A session in the household's list: the session screen's sidebar."""

    id: uuid.UUID
    title: str
    household_date: date
    started_at: datetime
    ended_at: datetime | None
    turns: int
    last_at: datetime


class StepOut(BaseModel):
    """One tool call by one agent, as `agent_step` logged it."""

    seq: int
    agent: str
    tool: str
    input_summary: str
    result_summary: str
    outcome: str
    at: datetime


class PersonRef(BaseModel):
    id: uuid.UUID
    display_name: str


class KeptTurnOut(BaseModel):
    """A turn kept in the session: the household's message, who wrote it, the answer as shown
    then, and the agents' steps."""

    seed: str
    said_by: PersonRef | None
    message: str
    at: datetime
    answer: TurnOut
    steps: list[StepOut]


class RunningOut(BaseModel):
    """The session's turn running now, with the steps its agents have taken so far."""

    seed: str
    said_by: uuid.UUID | None
    message: str
    started_at: datetime
    steps: list[StepOut]


class TurnsOut(BaseModel):
    session: SessionSummaryOut
    turns: list[KeptTurnOut]
    running: RunningOut | None


class PartOut(BaseModel):
    step: str
    ms: int
    n: int | None


class SpanOut(BaseModel):
    tool: str
    agent_id: str
    at: datetime
    ms: int
    ok: bool
    error_code: str
    parts: list[PartOut]


class TraceOut(BaseModel):
    session_id: uuid.UUID
    meko_conversation_id: str | None
    source: Literal["local_call_log", "cloud_trace_page", "none"]
    trace_url: str | None
    spans: list[SpanOut]
    truncated: bool = False  # the call log was read only in part (its page or time bound)


def _session_out(services: Services, s: Started) -> SessionOut:
    conversation = s.conversation_id if s.in_meko else None
    return SessionOut(
        id=s.session_id,
        household_id=s.household_id,
        title=s.title,
        household_date=s.on,
        meko_conversation_id=conversation,
        trace_url=services.settings.meko_trace_url(conversation) if conversation else None,
    )


async def _household(engine: AsyncEngine, household_id: uuid.UUID | None) -> tuple[uuid.UUID, date]:
    async with engine.connect() as conn:
        query = select(HOUSEHOLD.c.id, HOUSEHOLD.c.as_of_date).order_by(HOUSEHOLD.c.created_at)
        if household_id is not None:
            query = query.where(HOUSEHOLD.c.id == household_id)
        rows = (await conn.execute(query.limit(2))).all()
    if not rows:
        raise HTTPException(404, "no such household")
    if household_id is None and len(rows) > 1:
        raise HTTPException(422, "more than one household: name household_id")
    return rows[0][0], rows[0][1]


async def _started(services: Services, session_id: uuid.UUID) -> Started:
    try:
        return await load_session(services.engine, session_id)
    except SessionError as exc:
        status = 404 if "no such" in str(exc) else 409
        raise HTTPException(status, str(exc)) from None


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(body: NewSession, request: Request) -> SessionOut:
    """Start a planning session for the household: a Meko conversation and its row."""
    services = _services(request)
    household_id, as_of = await _household(services.engine, body.household_id)
    calls = DbCallLog(services.engine)
    try:
        async with services.open_meko(calls, 1) as meko:
            started = await start_session(
                services.engine,
                meko,
                household_id=household_id,
                on=body.household_date or as_of,
                title=body.title,
                call_log=calls,
            )
    except MekoError as exc:
        raise HTTPException(502, f"Meko: {safe_error(exc)}") from None
    return _session_out(services, started)


@router.get("", response_model=list[SessionSummaryOut])
async def read_sessions(
    request: Request, household_id: uuid.UUID | None = None
) -> list[SessionSummaryOut]:
    """The household's sessions, the most recently active first."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        rows = await list_sessions(conn, household)
    return [SessionSummaryOut(**row.__dict__) for row in rows]


def _step_out(step: StepRow) -> StepOut:
    return StepOut(
        seq=step.seq,
        agent=step.agent,
        tool=step.tool,
        input_summary=step.input_summary,
        result_summary=step.result_summary,
        outcome=step.outcome,
        at=step.created_at,
    )


@router.get("/{session_id}/turns", response_model=TurnsOut)
async def read_session_turns(session_id: uuid.UUID, request: Request) -> TurnsOut:
    """The session's turns as the household saw them, each with its agents' steps; and the turn
    running now, if it is this session's, with the steps taken so far."""
    services = _services(request)
    running = services.running
    async with services.engine.connect() as conn:
        household = (
            await conn.execute(select(SESSION.c.household_id).where(SESSION.c.id == session_id))
        ).scalar_one_or_none()
        if household is None:
            raise HTTPException(404, "no such session")
        summary = next(r for r in await list_sessions(conn, household) if r.id == session_id)
        turns = await read_turns(conn, session_id)
        live = None
        if running is not None and running.session_id == session_id:
            steps = await read_steps(conn, session_id, [running.seed])
            live = RunningOut(
                seed=running.seed,
                said_by=running.said_by,
                message=running.message,
                started_at=running.started_at,
                steps=[_step_out(s) for s in steps.get(running.seed, ())],
            )
    return TurnsOut(
        session=SessionSummaryOut(**summary.__dict__),
        turns=[
            KeptTurnOut(
                seed=t.seed,
                said_by=PersonRef(id=t.said_by, display_name=t.said_by_name or "")
                if t.said_by is not None
                else None,
                message=t.message,
                at=t.created_at,
                answer=TurnOut.model_validate(t.shown),
                steps=[_step_out(s) for s in t.steps],
            )
            for t in turns
        ],
        running=None if live is None or any(t.seed == live.seed for t in turns) else live,
    )


@router.get("/{session_id}", response_model=SessionOut)
async def read_session(session_id: uuid.UUID, request: Request) -> SessionOut:
    services = _services(request)
    return _session_out(services, await _started(services, session_id))


@router.post("/{session_id}/turns", response_model=TurnOut)
async def take_turn(session_id: uuid.UUID, body: NewTurn, request: Request) -> TurnOut:
    """Answer the household's message in the session. One turn runs at a time."""
    services = _services(request)
    session = await _started(services, session_id)
    if services.turn_lock.locked():
        raise HTTPException(429, "a turn is already running; try again when it ends")
    async with services.turn_lock:
        seed = await _seed(services.engine, session_id, body.seed)
        if body.person_id is not None:
            await _person(services.engine, session.household_id, body.person_id)
        services.running = Running(
            session_id, seed, body.message, body.person_id, datetime.now(UTC)
        )
        try:
            async with services.open_meko(
                DbCallLog(services.engine, session_id), MEKO_CALLS
            ) as meko:
                if meko is None and session.in_meko:
                    raise HTTPException(409, "this session has a Meko conversation; Meko is off")
                asked = await run_turn(
                    services.engine,
                    meko,
                    services.settings,
                    services.backend(),
                    session,
                    message=body.message,
                    known_at=body.known_at,
                    seed=seed,
                    speaker=body.person_id,
                )
        except SessionError as exc:
            raise HTTPException(409, str(exc)) from None
        except (ModelError, MekoError, BriefStoreError, OrchestratorError) as exc:
            raise HTTPException(502, f"the turn stopped: {safe_error(exc)}") from None
        finally:
            services.running = None
    return asked.shown or turn_shown(asked, services.settings)


async def _person(engine: AsyncEngine, household_id: uuid.UUID, person_id: uuid.UUID) -> None:
    async with engine.connect() as conn:
        found = (
            await conn.execute(
                select(PERSON.c.id).where(
                    PERSON.c.id == person_id, PERSON.c.household_id == household_id
                )
            )
        ).first()
    if found is None:
        raise HTTPException(422, "person_id: no such person in this household")


async def _seed(engine: AsyncEngine, session_id: uuid.UUID, asked: str | None) -> str:
    """The turn's seed: as asked (a recorded demo replays by it), else t1, t2… in the session."""
    async with engine.connect() as conn:
        used = set(
            (
                await conn.execute(
                    select(func.distinct(LLM_CALL.c.meko_turn_seed)).where(
                        LLM_CALL.c.session_id == session_id
                    )
                )
            ).scalars()
        )
    if asked is not None:
        if not SEED.fullmatch(asked):
            raise HTTPException(422, "seed: 1 to 40 of a-z, 0-9, ':', '_' or '-'")
        if asked in used:
            raise HTTPException(409, f"seed {asked!r} is already a turn of this session")
        return asked
    n = len(used) + 1
    while f"t{n}" in used:
        n += 1
    return f"t{n}"


class EndOut(BaseModel):
    session_id: uuid.UUID
    ended_at: datetime
    dream_run_id: uuid.UUID
    dream_status: str  # queued until `kako dream run` runs it; done or failed after


@router.post("/{session_id}/end", response_model=EndOut)
async def end(session_id: uuid.UUID, request: Request) -> EndOut:
    """End the session (no more turns) and queue its dreaming run, once: ending it again
    answers with the same run."""
    services = _services(request)
    async with services.turn_lock:  # never while one of its turns is running
        try:
            run_id = await end_session(services.engine, session_id, datetime.now(UTC))
        except DreamError as exc:
            raise HTTPException(404, str(exc)) from None
    async with services.engine.connect() as conn:
        row = (
            await conn.execute(
                select(SESSION.c.ended_at, DREAM_RUN.c.status)
                .join(DREAM_RUN, DREAM_RUN.c.session_id == SESSION.c.id)
                .where(SESSION.c.id == session_id)
            )
        ).one()
    return EndOut(
        session_id=session_id, ended_at=row.ended_at, dream_run_id=run_id, dream_status=row.status
    )


@router.get("/{session_id}/trace", response_model=TraceOut)
async def read_trace(session_id: uuid.UUID, request: Request) -> TraceOut:
    """The session's Meko calls as spans: from local Meko's call log, or a link to Meko Cloud's
    trace page."""
    services = _services(request)
    async with services.engine.connect() as conn:
        row = (
            await conn.execute(
                select(SESSION.c.meko_conversation_id, SESSION.c.started_at).where(
                    SESSION.c.id == session_id
                )
            )
        ).one_or_none()
    if row is None:
        raise HTTPException(404, "no such session")
    conversation, started_at = row
    if conversation.startswith(LOCAL_PREFIX):
        return TraceOut(
            session_id=session_id,
            meko_conversation_id=None,
            source="none",
            trace_url=None,
            spans=[],
        )
    settings = services.settings
    if settings.meko_target == "cloud":
        return TraceOut(
            session_id=session_id,
            meko_conversation_id=conversation,
            source="cloud_trace_page",
            trace_url=settings.meko_trace_url(conversation),
            spans=[],
        )
    try:
        trace = await local_trace(services.http, settings, conversation, since=started_at)
    except (MekoError, httpx.HTTPError) as exc:
        raise HTTPException(502, f"Meko: {safe_error(exc)}") from None
    return TraceOut(
        session_id=session_id,
        meko_conversation_id=conversation,
        source="local_call_log",
        trace_url=None,
        spans=[
            SpanOut(
                tool=s.tool,
                agent_id=s.agent_id,
                at=s.at,
                ms=s.ms,
                ok=s.ok,
                error_code=s.error_code,
                parts=[PartOut(step=p.step, ms=p.ms, n=p.n) for p in s.parts],
            )
            for s in trace.spans
        ],
        truncated=trace.truncated,
    )


def services_from(settings: Settings, engine: AsyncEngine, http: httpx.AsyncClient) -> Services:
    """The real services: Meko over MCP (counted in `meko_call`), and the model backend
    `KAKO_MODEL_MODE` asks for, built per turn."""
    from kako.agents.model_manager import chat_backend
    from kako.meko.mcp import open_meko

    @asynccontextmanager
    async def meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
        async with open_meko(settings, log, max_calls=max_calls) as adapter:
            yield adapter

    return Services(settings, engine, meko, lambda: chat_backend(settings), http, asyncio.Lock())
