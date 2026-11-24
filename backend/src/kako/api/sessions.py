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
from datetime import date, datetime
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
from kako.agents.ask import Asked as AskedTurn
from kako.agents.brief_store import BriefStoreError
from kako.agents.chat import ModelError
from kako.agents.orchestrator import OrchestratorError
from kako.agents.present import money
from kako.agents.reconciling import LABELS
from kako.agents.recorded import ChatBackend
from kako.agents.replan import changes_lines, why_lines
from kako.agents.tools import MESSAGE_CHARS
from kako.db.meko_log import DbCallLog
from kako.db.models import Household, LlmCall, Person, Session
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


@dataclass
class Services:
    """What the session routes use, built from settings (or by a test)."""

    settings: Settings
    engine: AsyncEngine
    open_meko: OpenMeko
    backend: Callable[[], ChatBackend]
    http: httpx.AsyncClient  # for local Meko's call log
    turn_lock: asyncio.Lock


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


class AllocationOut(BaseModel):
    entity: str
    centavos: int
    shown: str
    spec: str


class SourceOut(BaseModel):
    kind: str
    ref: str
    shown: str


class OptionOut(BaseModel):
    label: str
    summary: str
    what_if: str
    recommended: bool
    allocations: list[AllocationOut]
    sources: list[SourceOut]
    specialists: list[str]
    recommendation_ids: list[uuid.UUID]


class ResolutionOut(BaseModel):
    conflicts: list[str]
    described: list[str]
    together: str
    splits: list[str]
    chosen: str | None
    rejected: str | None
    reason: str
    reconciliation_ids: list[uuid.UUID]


class FlaggedOut(BaseModel):
    text: str
    where: str


class ProposalOut(BaseModel):
    specialist: str
    what_if: str | None
    summary: str


class ChangeOut(BaseModel):
    """A change the household stated, pending until a person approves it (`/api/v1/proposals`)."""

    proposal_id: uuid.UUID
    kind: str
    shown: str


class ReplanOut(BaseModel):
    """A replan's other two parts: what changed (from code's diff) and why."""

    since: str
    what_changed: list[str]
    why: str | None  # the orchestrator's, number-checked
    because: list[str]  # the facts behind it and the decisions to revisit, from code
    before_run_id: uuid.UUID | None
    revisit_decision_ids: list[uuid.UUID]


class PlanOut(BaseModel):
    id: uuid.UUID
    version: int
    status: Literal["proposed"]


class MekoTurnOut(BaseModel):
    conversation_id: str | None
    message_id: str | None
    error: str | None
    trace_url: str | None


class CostOut(BaseModel):
    model_calls: int
    input_tokens: int
    output_tokens: int
    usd: str  # a decimal string: money is never a float


class TurnOut(BaseModel):
    session_id: uuid.UUID
    seed: str
    reply: str
    options: list[OptionOut]
    recommended: str | None
    resolution: ResolutionOut | None
    flagged: list[FlaggedOut]
    proposals: list[ProposalOut]
    changes: list[ChangeOut]  # waiting for the household's yes
    not_proposed: list[str]  # changes the store refused, with why
    replan: ReplanOut | None
    plan: PlanOut | None
    calc_run_id: uuid.UUID | None
    meko: MekoTurnOut
    cost: CostOut


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
    return _turn_out(services, asked)


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


def _turn_out(services: Services, asked: AskedTurn) -> TurnOut:
    answer, saved = asked.answer, asked.saved
    recs = saved.recommendations if saved is not None else {}
    options = [
        OptionOut(
            label=o.label,
            summary=o.summary,
            what_if=o.what_if,
            recommended=o.label == answer.recommended,
            allocations=[
                AllocationOut(
                    entity=a.entity_ref, centavos=a.centavos, shown=money(a.centavos), spec=a.spec
                )
                for a in o.allocations
            ],
            sources=[SourceOut(kind=c.kind, ref=c.ref, shown=c.shown) for c in o.citations],
            specialists=list(o.specialists),
            recommendation_ids=list(recs.get(o.label, ())),
        )
        for o in answer.options
    ]
    resolution = None
    if answer.resolution is not None:
        r = answer.resolution
        resolution = ResolutionOut(
            conflicts=[LABELS[c.kind] for c in r.conflicts],
            described=list(r.described),
            together=r.together,
            splits=[f"{s.what_if}: {'fits' if s.fits else 'refused'}" for s in r.splits],
            chosen=r.chosen,
            rejected=r.rejected,
            reason=r.reason,
            reconciliation_ids=list(saved.reconciliations) if saved is not None else [],
        )
    checks = [*answer.checks, *(p.check for p in answer.proposals if p.check is not None)]
    flagged = [FlaggedOut(text=n.text, where=c.label) for c in checks for n in c.unmatched]
    plan = None
    if saved is not None and saved.plan_id is not None and saved.version is not None:
        plan = PlanOut(id=saved.plan_id, version=saved.version, status="proposed")
    replan = None
    if asked.replan is not None and asked.state is not None:
        entities = asked.state.entities
        replan = ReplanOut(
            since=asked.replan.since,
            what_changed=[line[2:] for line in changes_lines(asked.replan, entities)[1:]],
            why=answer.why,
            because=[line[2:] for line in why_lines(asked.replan, entities)[1:]],
            before_run_id=asked.before_run_id,
            revisit_decision_ids=[r.decision_id for r in asked.replan.revisit],
        )
    conversation = asked.conversation_id
    in_meko = conversation is not None and not conversation.startswith(LOCAL_PREFIX)
    return TurnOut(
        session_id=asked.session_id,
        seed=asked.seed,
        reply=answer.reply,
        options=options,
        recommended=answer.recommended,
        resolution=resolution,
        flagged=flagged,
        proposals=[
            ProposalOut(specialist=p.specialist, what_if=p.what_if, summary=p.summary)
            for p in answer.proposals
        ],
        changes=[
            ChangeOut(proposal_id=p.proposal_id, kind=p.kind, shown=p.shown)
            for p in asked.proposed
        ],
        not_proposed=list(asked.proposal_errors),
        replan=replan,
        plan=plan,
        calc_run_id=asked.calc_run_id,
        meko=MekoTurnOut(
            conversation_id=conversation if in_meko else None,
            message_id=asked.meko_message_id,
            error=asked.meko_error,
            trace_url=services.settings.meko_trace_url(conversation)
            if in_meko and conversation
            else None,
        ),
        cost=CostOut(
            model_calls=asked.model_calls,
            input_tokens=asked.input_tokens,
            output_tokens=asked.output_tokens,
            usd=f"{asked.cost_usd:.6f}",
        ),
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
