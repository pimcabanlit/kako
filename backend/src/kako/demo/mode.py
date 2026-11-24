"""Demo mode (Phase 3, task 9): the scripted sessions on local Meko, with recorded answers.

`kako demo run` is one command for judges and for the video's dry runs. It needs local Postgres (an
empty database, or one demo mode set up before) and local Meko running, and no Azure settings at
all: every model reply comes from a recording in `data/recorded/`, replayed strictly, so the turns
are the ones recorded on Foundry. It:

1. loads the demo household with its whole story (`prepare`), unless this database holds it already;
2. uploads the demo's documents to Meko's knowledge base (each file once: a second run adds none);
3. plays what dreaming learns in the story (`learning.toml`, `learn`) before the first session that
   starts after it: the dreaming run over session 3 proposes the preference, Mara approves it, Jun
   confirms its sharing, and the preference and a decision record are shared in Meko;
4. replays each session in `data/demo-household/sessions/` that has its recording, each turn kept
   like any other: the plan in Postgres, the turn in a new Meko conversation. A turn with an
   `approve` step has what it proposed approved, at its time in the story, by the adult it names.
   The rows of `changes.csv` such a session writes are left out when the story is loaded, and
   checked against what it wrote; on a database where they are written already, the session isn't
   replayed again;
5. with `--test-set`, replays the agent test set for each architecture that has its recording.

Each reply is found by its call's key (turn seed, agent, call number). A request can differ from the
one recorded when this machine's Meko ranks the brief's search results differently (the scores of
near-equal excerpts depend on the CPU), so by default the reply is replayed anyway and the calls
whose request differed are counted and reported. `--strict` refuses them instead, as the tests on
the recording machine do.

Asking anything else needs live mode with a Foundry deployment (`kako ask`, `kako api`).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Final, cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import MEKO_CALLS, Asked, run_turn, start_session
from kako.agents.chat import ChatReply, ChatRequest, ModelError
from kako.agents.recorded import ChatBackend, ReplayBackend
from kako.api.proposals import people
from kako.db.meko_log import DbCallLog
from kako.db.models import Entity, Household, Proposal, Session
from kako.db.proposal_store import ProposalError, approve
from kako.demo.files import Change, DemoHousehold
from kako.demo.kb import AGENT, upload_demo_documents
from kako.demo.load import load_demo
from kako.demo.sessions import DemoLearning, DemoSession
from kako.dreaming import job as dreaming
from kako.dreaming.promotion import propose_promotions
from kako.facts.proposals import FACT_KINDS, PayloadError, parse_fact, parse_life_event
from kako.meko.mcp import open_meko
from kako.settings import Settings
from kako.upkeep import sync as upkeep
from kako.upkeep.promote import SHARE_CALLS, share, shares_owed

HOUSEHOLD = cast(Table, Household.__table__)
ENTITY = cast(Table, Entity.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
SESSION = cast(Table, Session.__table__)
STATUS_CHECKS: Final = 10


class DemoModeError(Exception):
    """Demo mode can't run here, such as on Meko Cloud or a database with part of the story."""


@dataclass(frozen=True)
class Replayed:
    asked: list[Asked]
    calls: int  # model calls replayed
    drifted: tuple[str, ...]  # their keys whose request differed from the recording (lenient)


@dataclass(frozen=True)
class Prepared:
    household_id: uuid.UUID
    loaded: bool  # False: the database held the demo already
    documents: int
    new_documents: int


def check_target(settings: Settings) -> None:
    """Demo mode runs on local Meko and replays: it never spends Meko Cloud or Foundry."""
    if settings.database_url is None:
        raise DemoModeError(
            "KAKO_DATABASE_URL is not set: point it at a local Postgres database for the demo"
        )
    if settings.meko_target != "local":
        raise DemoModeError(
            "demo mode runs on local Meko: set MEKO_MCP_URL to http://127.0.0.1:7777/mcp"
        )


def written_by_sessions(sessions: Collection[DemoSession]) -> frozenset[int]:
    """The changes the sessions that will replay write themselves: loading leaves them out."""
    return frozenset(n for s in sessions if s.recording.exists() for n in s.writes)


async def prepare(
    engine: AsyncEngine, settings: Settings, demo: DemoHousehold, *, skip: Collection[int] = ()
) -> Prepared:
    """The household with its whole story (but the changes in `skip`, which sessions write), and
    its documents searchable in Meko."""
    async with engine.connect() as conn:
        found = (
            await conn.execute(
                select(HOUSEHOLD.c.id).where(HOUSEHOLD.c.name == demo.household.name)
            )
        ).scalar_one_or_none()
        loaded = found is None
        if found is None:
            through = max(c.recorded_at for c in demo.changes) if demo.changes else None
            household_id = await load_demo(conn, demo, through=through, skip=skip)
            await conn.commit()
        else:
            household_id = found
            approved = (
                await conn.execute(
                    select(func.count()).where(
                        PROPOSAL.c.household_id == household_id, PROPOSAL.c.status == "approved"
                    )
                )
            ).scalar_one()
            if approved < len(demo.changes) - len(skip):
                raise DemoModeError(
                    f"this database holds {demo.household.name} with {approved} of its "
                    f"{len(demo.changes)} changes: demo mode needs the whole story, so use an "
                    "empty database"
                )
    calls = DbCallLog(engine)
    bound = 1 + len(demo.documents) * (1 + STATUS_CHECKS)
    async with open_meko(settings, calls, max_calls=bound) as meko:
        conversation_id = await meko.create_conversation(
            agent_id=AGENT, title="Demo knowledge base", session_key="kako-demo-kb"
        )
        documents = await upload_demo_documents(
            meko, demo, conversation_id, checks=STATUS_CHECKS, pause=2.0
        )
    new = sum(1 for d in documents if not d.already_uploaded)
    return Prepared(household_id, loaded, len(documents), new)


async def replay_session(
    engine: AsyncEngine,
    settings: Settings,
    demo: DemoHousehold,
    session: DemoSession,
    household_id: uuid.UUID,
    *,
    strict: bool = False,
    shown: Callable[[Asked], None] | None = None,
    backend: ChatBackend | None = None,
) -> Replayed:
    """One scripted session: a new session, each turn answered from its recording (or `backend`,
    for a test that records one)."""
    backend = backend or ReplayBackend(session.recording, strict=strict)
    replay = settings.model_copy(
        update={"model_mode": "replay", "recorded_responses": session.recording}
    )
    calls = DbCallLog(engine)
    asked: list[Asked] = []
    async with engine.connect() as conn:
        by_name = await people(conn, household_id)
    ids = {p.key: by_name[p.display_name.lower()] for p in demo.people}
    async with open_meko(replay, calls, max_calls=1 + MEKO_CALLS * len(session.turns)) as meko:
        started = await start_session(
            engine,
            meko,
            household_id=household_id,
            on=session.on,
            title=session.title,
            call_log=calls,
        )
        for turn in session.turns:
            answer = await run_turn(
                engine,
                meko,
                replay,
                backend,
                started,
                message=turn.message,
                known_at=session.known_at_of(turn),
                seed=turn.seed,
                speaker=ids[turn.speaker],
            )
            asked.append(answer)
            if shown is not None:
                shown(answer)
            if turn.approve is not None:
                if answer.proposal_errors or not answer.proposed:
                    raise DemoModeError(
                        f"{session.title}, turn {turn.seed}: nothing to approve"
                        + "".join(f"; {e}" for e in answer.proposal_errors)
                    )
                try:
                    async with engine.connect() as conn:
                        await approve(
                            conn,
                            [p.proposal_id for p in answer.proposed],
                            person_id=ids[turn.approve.by],
                            decided_at=turn.approve.at,
                        )
                        await conn.commit()
                except ProposalError as exc:
                    raise DemoModeError(f"{session.title}, turn {turn.seed}: {exc}") from None
    if session.writes:
        found = await written(engine, demo, session, household_id)
        missing = [n for n, key in found.items() if key is None]
        theirs = [
            n for n, key in found.items() if key and not key.startswith(str(started.session_id))
        ]
        if missing or theirs:
            raise DemoModeError(
                f"{session.title} didn't write changes.csv rows "
                + ", ".join(str(n) for n in [*missing, *theirs])
                + " as the story has them: record it again, or fix the rows"
            )
    drifted = backend.drifted if isinstance(backend, ReplayBackend) else []
    return Replayed(asked, sum(a.model_calls for a in asked), tuple(drifted))


async def written(
    engine: AsyncEngine, demo: DemoHousehold, session: DemoSession, household_id: uuid.UUID
) -> dict[int, str | None]:
    """For each change the session writes, the idempotency key of the approved proposal that wrote
    it as `changes.csv` has it (the same kind, entity, attribute, value and date), or None."""
    changes = {c.seq: c for c in demo.changes}
    names = {e.key: e.name for e in demo.entities}
    async with engine.connect() as conn:
        entities = {
            name: entity_id
            for name, entity_id in await conn.execute(
                select(ENTITY.c.name, ENTITY.c.id).where(ENTITY.c.household_id == household_id)
            )
        }
        rows = list(
            await conn.execute(
                select(PROPOSAL.c.kind, PROPOSAL.c.payload, PROPOSAL.c.idempotency_key).where(
                    PROPOSAL.c.household_id == household_id,
                    PROPOSAL.c.status == "approved",
                    PROPOSAL.c.kind.in_(("life_event", *FACT_KINDS)),
                )
            )
        )
    found: dict[int, str | None] = {}
    for seq in session.writes:
        change = changes[seq]
        entity_id = entities.get(names[change.entity]) if change.entity else None
        found[seq] = next(
            (key for kind, payload, key in rows if _is(change, entity_id, kind, payload)), None
        )
    return found


def _is(change: Change, entity_id: uuid.UUID | None, kind: str, payload: object) -> bool:
    """Whether an approved proposal writes `change` as the story has it."""
    if kind != change.kind:
        return False
    try:
        if kind == "life_event":
            event = parse_life_event(payload)
            return (event.kind, event.occurs_on) == (change.attribute, change.valid_from)
        fact = parse_fact(kind, payload)
    except PayloadError:
        return False
    return (fact.entity_id, fact.attribute, fact.value, fact.valid_from) == (
        entity_id,
        change.attribute,
        change.value,
        change.valid_from,
    )


@dataclass(frozen=True)
class Learned:
    already: bool  # an earlier run played it: nothing done
    pattern: uuid.UUID | None = None  # the preference proposal dreaming made, now approved
    promoted: int = 0  # promotions approved with their second confirmation
    shared: int = 0  # of them, shared in Meko


class _NoModel:
    """Dreaming over a session of the story calls no model: its session has no conversation."""

    @property
    def replays(self) -> bool:
        return True

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        raise ModelError("a session of the story has no turns to read: no model call is made")


async def learn(
    engine: AsyncEngine,
    settings: Settings,
    demo: DemoHousehold,
    learning: DemoLearning,
    household_id: uuid.UUID,
) -> Learned:
    """What dreaming learns in the story, played as it would happen: the dreaming run over the
    session proposes the pattern, which must be `changes.csv` row `learning.writes`; the row's adult
    approves it at the row's time; what that offers for sharing (and what the run offered) is
    approved with its second confirmation by `learning.promote.by`; then each is shared in Meko."""
    change = next(c for c in demo.changes if c.seq == learning.writes)
    async with engine.connect() as conn:
        by_name = await people(conn, household_id)
        session_id = (
            await conn.execute(
                select(SESSION.c.id).where(
                    SESSION.c.household_id == household_id, SESSION.c.title == learning.session
                )
            )
        ).scalar_one_or_none()
        done = (
            await conn.execute(
                select(PROPOSAL.c.payload).where(
                    PROPOSAL.c.household_id == household_id,
                    PROPOSAL.c.kind == change.kind,
                    PROPOSAL.c.status == "approved",
                )
            )
        ).all()
    if any(_is(change, None, change.kind, row.payload) for row in done):
        return Learned(already=True)
    if session_id is None:
        raise DemoModeError(f"no {learning.session} in this database to dream over")
    ids = {p.key: by_name[p.display_name.lower()] for p in demo.people}
    calls = DbCallLog(engine)
    run_id = await dreaming.end_session(engine, session_id, learning.dreamt_at)
    async with open_meko(settings, calls, max_calls=dreaming.MEKO_CALLS) as meko:
        report = await dreaming.run_dream(
            engine, meko, settings, _NoModel(), run_id, now=learning.dreamt_at
        )
    found = [o.proposal_id for o in report.patterns if o.status == "proposed" and o.proposal_id]
    if report.status != "done" or len(found) != 1:
        raise DemoModeError(
            f"dreaming over {learning.session} didn't propose one pattern "
            f"({report.status}, {len(found)} proposed): check decisions.toml"
        )
    (pattern,) = found
    try:
        async with engine.connect() as conn:
            payload = (
                await conn.execute(select(PROPOSAL.c.payload).where(PROPOSAL.c.id == pattern))
            ).scalar_one()
            if not _is(change, None, change.kind, payload):
                raise DemoModeError(
                    f"dreaming over {learning.session} proposed a preference that isn't "
                    f"changes.csv row {change.seq}: fix the row or decisions.toml"
                )
            await approve(
                conn, [pattern], person_id=ids[change.decided_by], decided_at=change.recorded_at
            )
            await conn.commit()
            await propose_promotions(conn, household_id, now=change.recorded_at)
            await conn.commit()
            offered = list(
                (
                    await conn.execute(
                        select(PROPOSAL.c.id)
                        .where(
                            PROPOSAL.c.household_id == household_id,
                            PROPOSAL.c.kind == "promote",
                            PROPOSAL.c.status == "pending",
                        )
                        .order_by(PROPOSAL.c.created_at, PROPOSAL.c.id)
                    )
                ).scalars()
            )
            if offered:
                await approve(
                    conn,
                    offered,
                    person_id=ids[learning.promote.by],
                    decided_at=learning.promote.at,
                    confirm_promotion=True,
                )
                await conn.commit()
            owed = await shares_owed(conn, household_id)
    except (ProposalError, PayloadError) as exc:
        raise DemoModeError(f"what dreaming learned in {learning.session}: {exc}") from None
    bound = 1 + sum(SHARE_CALLS[item.target] for item in owed)
    async with engine.connect() as conn:
        name = (
            await conn.execute(select(HOUSEHOLD.c.name).where(HOUSEHOLD.c.id == household_id))
        ).scalar_one()
    async with open_meko(settings, calls, max_calls=bound) as meko:
        conversation_id = await meko.create_conversation(
            agent_id=upkeep.AGENT,
            title=f"Kako's memory of the {name}",
            session_key=upkeep.session_key(household_id),
        )
        for item in owed:
            await share(
                engine,
                meko,
                household_id,
                conversation_id,
                item,
                agent=upkeep.AGENT,
                now=learning.promote.at,
            )
    return Learned(False, pattern, len(offered), len(owed))
