"""The dreaming job (docs/architecture.md, "How dreaming works"): one `dream_run` per ended session.

Ending a session queues its run (`end_session`); `run_dream` does it:

1. **Read** the session's turns from Meko (only the turns Kako kept for this session, with their
   seed, date and speaker), the household's facts and life events (and those waiting for a yes).
2. **Extract** claims: the one model step (`extract.py`).
3. **Check in code and classify** (`classify.py`): same, new, replace, retract or conflict.
4. **Propose** what is new as pending proposals with `dream_run_id`, the quote as evidence (who said
   it, in which turn) and the idempotency key of the turn it was said in. A proposal the session
   already made from the same words is **already**: dreaming never proposes it twice.
5. **Candidates.** The memories Meko extracted from the session on its own are shown to extraction
   as noted memories; each settles to waiting or delete (`candidates.py`), kept in the run's
   counts, and `memories.py` carries it out in Meko and `meko_link` (V-14).

The run is done once: a done run does nothing again; a failed one may run again, and what it
proposed the first time is found under its keys. The model and the household's words never
change a fact: a person approves each proposal (`db.proposal_store.approve`).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, cast

from sqlalchemy import Table, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.agents.ask import AGENT as CONVERSATION_AGENT
from kako.agents.ask import LOCAL_PREFIX
from kako.agents.model_manager import ModelManager
from kako.agents.present import Refs
from kako.agents.recorded import ChatBackend
from kako.agents.turn import StepLog, short
from kako.db.agent_steps import DbStepLog
from kako.db.fact_store import load_entities, load_facts
from kako.db.llm_log import DbLlmLog
from kako.db.models import DreamRun, Household, LifeEvent, Person, Proposal, Session
from kako.db.proposal_store import Evidence, ProposalError, propose
from kako.dreaming.candidates import MAX_NOTED, Candidate, Noted, Settled, noted_memories, settle
from kako.dreaming.claims import SaidTurn
from kako.dreaming.classify import PROPOSING, Finding, Known, classify
from kako.dreaming.extract import DreamInputs, Extraction, extract, said_turns
from kako.dreaming.promotion import PatternOutcome, propose_patterns, propose_promotions
from kako.facts.evidence import text_unquoted
from kako.facts.proposals import PayloadError, idempotency_key, parse_life_event
from kako.facts.snapshot import take_snapshot
from kako.health import safe_error
from kako.meko.adapter import Meko
from kako.settings import Settings

DREAM_RUN = cast(Table, DreamRun.__table__)
SESSION = cast(Table, Session.__table__)
HOUSEHOLD = cast(Table, Household.__table__)
PERSON = cast(Table, Person.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
LIFE_EVENT = cast(Table, LifeEvent.__table__)
MAX_LISTED: Final = 40  # findings kept in a run's counts
AGENT: Final = "kako:dreaming"
QUERY_CHARS: Final = 2_000  # the household's words, as the search for the session's memories
# Meko calls for one run and its settling: the turns, the memories, a delete for each.
MEKO_CALLS: Final = 2 + MAX_NOTED


class DreamError(Exception):
    """The run can't be done as asked (no such session, a session still open, no conversation)."""


@dataclass(frozen=True)
class Outcome:
    """One finding as the run reports it, with the proposals it made."""

    finding: Finding
    outcome: str  # the finding's, or `already` (the session proposed it) or `refused`
    reason: str
    proposal_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class DreamReport:
    dream_run_id: uuid.UUID
    session_id: uuid.UUID
    status: str  # done, failed, or the run's status when there was nothing to do
    ran: bool  # False: the run was done already (or running elsewhere), nothing was done
    outcomes: tuple[Outcome, ...] = ()
    model_calls: int = 0
    error: str | None = None
    candidates: tuple[Candidate, ...] = ()
    patterns: tuple[PatternOutcome, ...] = ()
    promotions: tuple[uuid.UUID, ...] = ()  # promote proposals made

    @property
    def proposed(self) -> tuple[uuid.UUID, ...]:
        """Every proposal the run made: from the session's words, its patterns and promotions."""
        patterns = tuple(p.proposal_id for p in self.patterns if p.proposal_id is not None)
        return tuple(i for o in self.outcomes for i in o.proposal_ids) + patterns + self.promotions


async def end_session(engine: AsyncEngine, session_id: uuid.UUID, at: datetime) -> uuid.UUID:
    """End a session (once) and queue its dreaming run (once): the run's id."""
    if at.tzinfo is None:
        raise DreamError("the end time must carry its time zone")
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                select(SESSION.c.id, SESSION.c.ended_at)
                .where(SESSION.c.id == session_id)
                .with_for_update()
            )
        ).first()
        if row is None:
            raise DreamError("no such session")
        if row.ended_at is None:
            await conn.execute(
                update(SESSION).where(SESSION.c.id == session_id).values(ended_at=at)
            )
        await conn.execute(
            insert(DREAM_RUN)
            .values(id=uuid.uuid4(), session_id=session_id, status="queued")
            .on_conflict_do_nothing(index_elements=["session_id"])
        )
        run_id = (
            await conn.execute(select(DREAM_RUN.c.id).where(DREAM_RUN.c.session_id == session_id))
        ).scalar_one()
    return cast(uuid.UUID, run_id)


async def queued_runs(engine: AsyncEngine) -> list[uuid.UUID]:
    """The runs waiting (queued, or failed and so to try again), oldest session first."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(DREAM_RUN.c.id)
            .join(SESSION, SESSION.c.id == DREAM_RUN.c.session_id)
            .where(DREAM_RUN.c.status.in_(("queued", "failed")))
            .order_by(SESSION.c.ended_at, DREAM_RUN.c.id)
        )
        return [r.id for r in rows]


async def _claim_run(engine: AsyncEngine, run_id: uuid.UUID, at: datetime) -> Any:
    """Mark the run running, if it is queued or failed; None when it isn't (done, or running)."""
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                update(DREAM_RUN)
                .where(DREAM_RUN.c.id == run_id, DREAM_RUN.c.status.in_(("queued", "failed")))
                .values(status="running", started_at=at, finished_at=None)
                .returning(DREAM_RUN.c.session_id)
            )
        ).first()
        return row


async def _finish(
    engine: AsyncEngine, run_id: uuid.UUID, status: str, at: datetime, counts: dict[str, Any]
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            update(DREAM_RUN)
            .where(DREAM_RUN.c.id == run_id)
            .values(status=status, finished_at=at, counts=counts)
        )


@dataclass(frozen=True)
class DreamSession:
    id: uuid.UUID
    household_id: uuid.UUID
    household_name: str
    conversation_id: str
    on: date
    datapack_id: str | None


async def read_session(conn: AsyncConnection, session_id: uuid.UUID) -> DreamSession:
    row = (
        await conn.execute(
            select(
                SESSION.c.id,
                SESSION.c.household_id,
                SESSION.c.meko_conversation_id,
                SESSION.c.household_date,
                SESSION.c.ended_at,
                HOUSEHOLD.c.name,
                HOUSEHOLD.c.meko_datapack_id,
            )
            .join(HOUSEHOLD, HOUSEHOLD.c.id == SESSION.c.household_id)
            .where(SESSION.c.id == session_id)
        )
    ).first()
    if row is None:
        raise DreamError("no such session")
    if row.ended_at is None:
        raise DreamError("the session hasn't ended: dreaming runs after it")
    return DreamSession(
        row.id,
        row.household_id,
        row.name,
        row.meko_conversation_id,
        row.household_date,
        row.meko_datapack_id,
    )


async def people(conn: AsyncConnection, household_id: uuid.UUID) -> list[Any]:
    rows = await conn.execute(
        select(PERSON.c.id, PERSON.c.display_name, PERSON.c.role)
        .where(PERSON.c.household_id == household_id)
        .order_by(PERSON.c.role, PERSON.c.display_name)
    )
    return list(rows)


async def household_known(
    conn: AsyncConnection, household_id: uuid.UUID, known_at: datetime | None
) -> tuple[Known, tuple[tuple[str, date, str], ...]]:
    """What Kako holds as known at `known_at`, as classification compares with it, and the life
    events it has (kind, day, description) for the brief. Life events waiting for a yes count, so
    a fact names the one the session already proposed."""
    facts = tuple(await load_facts(conn, household_id))
    entities = await load_entities(conn, household_id)
    refs = Refs.of(entities)
    events_query = select(
        LIFE_EVENT.c.id, LIFE_EVENT.c.kind, LIFE_EVENT.c.occurs_on, LIFE_EVENT.c.description
    ).where(LIFE_EVENT.c.household_id == household_id)
    pending_query = select(PROPOSAL.c.payload).where(
        PROPOSAL.c.household_id == household_id,
        PROPOSAL.c.kind == "life_event",
        PROPOSAL.c.status == "pending",
    )
    if known_at is not None:
        events_query = events_query.where(LIFE_EVENT.c.recorded_at <= known_at)
        pending_query = pending_query.where(PROPOSAL.c.created_at <= known_at)
    events = list(await conn.execute(events_query))
    pending = [parse_life_event(r.payload) for r in await conn.execute(pending_query)]
    known = Known(
        household_id,
        facts,
        {refs.by_id[e.id]: e for e in entities},
        (
            *((e.id, e.kind, e.occurs_on) for e in events),
            *((p.id, p.kind, p.occurs_on) for p in pending),
        ),
        known_at,
    )
    return known, tuple((e.kind, e.occurs_on, e.description) for e in events)


async def session_turns(
    meko: Meko, session: DreamSession, names: dict[uuid.UUID, str]
) -> list[SaidTurn]:
    """The household's turns Kako kept for this session, in order: a message with no seed, or
    one that names another session, isn't one of them."""
    if session.conversation_id.startswith(LOCAL_PREFIX):
        raise DreamError("the session has no Meko conversation to read its turns from")
    if session.datapack_id is not None and meko.datapack_id != session.datapack_id:
        raise DreamError("Meko isn't on this household's datapack")
    turns = []
    # Meko answers conversation_get only to the agent that created the conversation (the
    # orchestrator, tested on local Meko 1.20261116.0); dreaming's own writes use its own id.
    for turn in await meko.read_turns(session.conversation_id, agent_id=CONVERSATION_AGENT):
        meta = turn.metadata
        seed = meta.get("kako_turn")
        if not isinstance(seed, str) or meta.get("kako_session_id") != str(session.id):
            continue
        person: uuid.UUID | None = None
        try:
            person = uuid.UUID(str(meta["kako_said_by"])) if "kako_said_by" in meta else None
        except ValueError:
            person = None
        if person not in names:
            person = None
        try:
            on = date.fromisoformat(str(meta.get("kako_household_date")))
        except ValueError:
            on = session.on
        turns.append(SaidTurn(seed, turn.input, on, person, names.get(person) if person else None))
    return turns


def memory_query(turns: Sequence[SaidTurn]) -> str:
    """What finds the session's memories: the household's own words (Meko extracts from them)."""
    return " ".join(t.text for t in turns)[:QUERY_CHARS]


async def session_noted(
    meko: Meko, conversation_id: str, turns: Sequence[SaidTurn]
) -> tuple[Noted, ...]:
    """The memories Meko extracted from the session on its own (one search), as candidates."""
    if not turns:
        return ()
    found = await meko.search_memories(conversation_id, memory_query(turns), agent_id=AGENT)
    return noted_memories(found, conversation_id)


async def dream_over(
    manager: ModelManager,
    steps: StepLog,
    *,
    session_id: uuid.UUID | None,
    inputs: DreamInputs,
    known: Known,
) -> tuple[Extraction, list[Finding]]:
    """Extraction and the checks over some turns: the claims and what dreaming makes of them.
    The run's model calls are keyed `dream:<first turn's seed>/extract/<n>`, so a recording
    replays on any database."""
    if not inputs.turns:
        return Extraction((), 0), []
    turn = manager.turn(f"dream:{inputs.turns[0].seed}", session_id=session_id, steps=steps)
    extraction = await extract(manager, turn, inputs)
    if extraction.claims is None:
        return extraction, []
    return extraction, classify(extraction.claims, inputs.turns, known, new_id=uuid.uuid4)


async def _existing(conn: AsyncConnection, keys: Sequence[str]) -> dict[str, uuid.UUID]:
    if not keys:
        return {}
    rows = await conn.execute(
        select(PROPOSAL.c.idempotency_key, PROPOSAL.c.id).where(
            PROPOSAL.c.idempotency_key.in_(list(keys))
        )
    )
    return {r.idempotency_key: r.id for r in rows}


def _noted_evidence(noted: Sequence[Noted], f: Finding) -> list[Evidence]:
    """The noted memories a claim names, as evidence the household sees (never a quote for
    V-09), when they hold no number the claim's quote doesn't."""
    if f.turn is None:
        return []
    return [
        Evidence("extracted_memory", n.memory_id, n.text)
        for n in noted
        if not text_unquoted(n.text, [f.quote], today=f.turn.said_on)
    ]


async def _propose(
    engine: AsyncEngine,
    session: DreamSession,
    run_id: uuid.UUID,
    findings: list[Finding],
    at: datetime,
    named: dict[int, list[Noted]] | None = None,
) -> list[Outcome]:
    """Each claim's proposals in one transaction (a life event with its facts, a retraction with
    the value that takes its place), checked again by the store. Refused: reported, never
    dropped."""
    outcomes: list[Outcome] = []
    by_claim: dict[int, list[Finding]] = {}
    for f in findings:
        if f.outcome in PROPOSING and f.turn is not None:
            by_claim.setdefault(f.claim, []).append(f)
        else:
            outcomes.append(Outcome(f, f.outcome, f.reason))
    for group in by_claim.values():
        keyed = [
            (f, p, idempotency_key(f"{session.id}:{f.turn.seed}", p.kind, p.target))
            for f in group
            if f.turn is not None
            for p in f.proposals
        ]
        async with engine.connect() as conn:
            existing = await _existing(conn, [k for _, _, k in keyed])
        fresh = {id(f) for f in group if not any(k in existing for g, _, k in keyed if g is f)}
        for f in group:
            if id(f) not in fresh:
                outcomes.append(Outcome(f, "already", "proposed in the session already"))
        if not fresh:
            continue
        made: dict[int, list[uuid.UUID]] = {}
        try:
            async with engine.begin() as conn:
                for f, p, key in keyed:
                    if id(f) not in fresh or f.turn is None:
                        continue
                    evidence = [
                        Evidence(
                            "turn",
                            f"{session.conversation_id}:{f.turn.seed}",
                            f.quote,
                            f.turn.person_id,
                        ),
                        *(Evidence("fact", str(e.fact_id), e.quote) for e in f.evidence),
                        *_noted_evidence((named or {}).get(f.claim, ()), f),
                    ]
                    done = await propose(
                        conn,
                        household_id=session.household_id,
                        kind=p.kind,
                        payload=p.payload,
                        explanation=f"Dreaming found it in the session: “{short(f.quote, 280)}”",
                        idempotency_key=key,
                        evidence=evidence,
                        today=f.turn.said_on,
                        created_at=at,
                        dream_run_id=run_id,
                    )
                    made.setdefault(id(f), []).append(done.proposal_id)
        except (ProposalError, PayloadError) as exc:
            outcomes += [
                Outcome(f, "refused", f"the store refused it: {exc}")
                for f in group
                if id(f) in fresh
            ]
            continue
        outcomes += [
            Outcome(f, f.outcome, f.reason, tuple(made.get(id(f), ())))
            for f in group
            if id(f) in fresh
        ]
    order = {id(f): n for n, f in enumerate(findings)}
    return sorted(outcomes, key=lambda o: order[id(o.finding)])


def _named(noted: Sequence[Noted], extraction: Extraction) -> dict[int, list[Noted]]:
    """The noted memories each claim names (by its position from 1); unknown refs are dropped."""
    by_ref = {n.ref: n for n in noted}
    return {
        c: [by_ref[r] for r in claim.memories if r in by_ref]
        for c, claim in enumerate(extraction.claims or (), start=1)
        if any(r in by_ref for r in claim.memories)
    }


def _fates(
    noted: Sequence[Noted],
    named: dict[int, list[Noted]],
    extraction: Extraction,
    outcomes: Sequence[Outcome],
    on: date,
) -> list[Candidate]:
    """Each noted memory's fate, from what the claims that name it came to."""
    claims = extraction.claims or ()
    by_ref: dict[str, list[Settled]] = {}
    for c, memories in named.items():
        mine = [o for o in outcomes if o.finding.claim == c]
        said_on = next((o.finding.turn.said_on for o in mine if o.finding.turn), on)
        settled = Settled(
            claims[c - 1].quote,
            said_on,
            tuple(dict.fromkeys(i for o in mine for i in o.proposal_ids)),
        )
        for n in memories:
            by_ref.setdefault(n.ref, []).append(settled)
    return settle(noted, by_ref)


def candidate_json(c: Candidate) -> dict[str, Any]:
    """A candidate as the run keeps it; `state` moves on as `memories.py` carries it out."""
    return {
        "ref": c.noted.ref,
        "memory_id": c.noted.memory_id,
        "agent_id": c.noted.agent_id,
        "text": short(c.noted.text, 200),
        "fate": c.fate,
        "state": c.fate,
        "reason": short(c.reason, 200),
        "proposal_ids": [str(i) for i in c.proposal_ids],
    }


def _counts(
    outcomes: Sequence[Outcome], extraction: Extraction, candidates: Sequence[Candidate] = ()
) -> dict[str, Any]:
    kinds = Counter(p.kind for o in outcomes if o.proposal_ids for p in o.finding.proposals)
    return {
        "memories": [candidate_json(c) for c in candidates],
        "claims": len(extraction.claims or ()),
        "model_calls": extraction.model_calls,
        "proposals": dict(sorted(kinds.items())),
        "outcomes": dict(sorted(Counter(o.outcome for o in outcomes).items())),
        "findings": [
            {
                "claim": o.finding.claim,
                "turn": o.finding.turn.seed if o.finding.turn else None,
                "outcome": o.outcome,
                "shown": short(o.finding.shown, 200),
                "reason": short(o.reason, 200),
            }
            for o in outcomes[:MAX_LISTED]
        ],
    }


async def run_dream(
    engine: AsyncEngine,
    meko: Meko,
    settings: Settings,
    backend: ChatBackend,
    run_id: uuid.UUID,
    *,
    now: datetime,
) -> DreamReport:
    """Run one queued (or failed) dreaming run at `now` (the time its proposals are made). A run
    that is done, or running elsewhere, does nothing."""
    if now.tzinfo is None:
        raise DreamError("now must carry its time zone")
    claimed = await _claim_run(engine, run_id, now)
    if claimed is None:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(DREAM_RUN.c.session_id, DREAM_RUN.c.status).where(
                        DREAM_RUN.c.id == run_id
                    )
                )
            ).first()
        if row is None:
            raise DreamError("no such dreaming run")
        return DreamReport(run_id, row.session_id, row.status, ran=False)
    session_id = claimed.session_id
    try:
        async with engine.connect() as conn:
            session = await read_session(conn, session_id)
            household = await people(conn, session.household_id)
            known, events = await household_known(conn, session.household_id, now)
        names = {p.id: p.display_name for p in household}
        # A session with no Meko conversation (one written outside a planning turn, such as a
        # decision of the demo's story) has no turns to read: its run is steps 4 and 5 alone.
        local = session.conversation_id.startswith(LOCAL_PREFIX)
        turns = () if local else said_turns(await session_turns(meko, session, names))
        noted = await session_noted(meko, session.conversation_id, turns)
        inputs = DreamInputs(
            session.household_name,
            tuple((p.display_name, p.role) for p in household),
            session.on,
            tuple(known.entities.values()),
            take_snapshot(session.household_id, known.facts, session.on, now).facts,
            events,
            turns,
            noted,
        )
        manager = ModelManager(settings, backend, DbLlmLog(engine))
        extraction, findings = await dream_over(
            manager,
            DbStepLog(engine, session.id),
            session_id=session.id,
            inputs=inputs,
            known=known,
        )
        if extraction.claims is None:
            raise DreamError("the extraction step handed in no claims")
        named = _named(noted, extraction)
        outcomes = await _propose(engine, session, run_id, findings, now, named)
        candidates = _fates(noted, named, extraction, outcomes, session.on)
        async with engine.begin() as conn:
            patterns = await propose_patterns(
                conn, session.household_id, on=session.on, now=now, dream_run_id=run_id
            )
            promotions = await propose_promotions(
                conn, session.household_id, now=now, dream_run_id=run_id
            )
    except Exception as exc:
        error = safe_error(exc)
        await _finish(engine, run_id, "failed", now, {"error": error})
        raise
    counts = _counts(outcomes, extraction, candidates)
    counts["patterns"] = [pattern_json(p) for p in patterns]
    counts["promotions"] = [str(i) for i in promotions]
    await _finish(engine, run_id, "done", now, counts)
    return DreamReport(
        run_id,
        session_id,
        "done",
        True,
        tuple(outcomes),
        extraction.model_calls,
        candidates=tuple(candidates),
        patterns=tuple(patterns),
        promotions=tuple(promotions),
    )


def pattern_json(outcome: PatternOutcome) -> dict[str, Any]:
    return {
        "attribute": outcome.pattern.attribute,
        "value": outcome.pattern.value,
        "status": outcome.status,
        "proposal_id": str(outcome.proposal_id) if outcome.proposal_id else None,
        "decisions": [str(c.decision_id) for c in outcome.pattern.choices],
    }
