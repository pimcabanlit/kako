"""Context Gaps on Postgres and Meko (docs/data-model.md, `context_gap`).

- `collect_gaps` reads Meko's search log (`selflearning_query_log`, the low and the mid band: two
  calls) and keeps each search worth asking about (`questions.py`) as an `open` gap with its band,
  its best score and the question, once per logged search.
- `answer_gap` ties a gap to the proposal that answers it, a change to the household's facts, and
  marks it `answered`; `dismiss_gap` closes one an adult says isn't worth answering.
- `verify_gaps` replays each answered search once its proposal is approved and Meko upkeep has
  written the facts' memories (`selflearning_verify`, one search each, at most `MAX_REPLAYS` a
  run), and keeps Meko's outcome and the score after. A gap whose search now matches better is
  `verified`; one Meko is still indexing waits for the next run.

Self-learning is served by Meko Cloud, not local Meko: there each call raises
`SelfLearningUnavailable`, and nothing is changed. Every call goes through the call counter, and a
replay counts as a `context_search`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Literal, cast

from sqlalchemy import Table, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.db.models import ContextGap, Fact, Household, MekoLink, Person, Proposal
from kako.facts.proposals import FACT_KINDS
from kako.gaps.questions import question, reason_of, worth_asking
from kako.meko.adapter import Meko
from kako.settings import Settings

GAP = cast(Table, ContextGap.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
FACT = cast(Table, Fact.__table__)
HOUSEHOLD = cast(Table, Household.__table__)
PERSON = cast(Table, Person.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
AGENT: Final = "kako:gaps"
MAX_REPLAYS: Final = 5
COLLECT_CALLS: Final = 3  # the conversation, then the low and the mid band
Status = Literal["open", "asked", "answered", "verified", "dismissed"]


class GapError(Exception):
    """A gap can't be changed this way."""


@dataclass(frozen=True)
class Gap:
    id: uuid.UUID
    query: str
    band_before: str
    score_before: Decimal
    reason: str
    question: str | None
    status: str
    proposal_id: uuid.UUID | None
    verify_outcome: str | None
    score_after: Decimal | None


@dataclass
class VerifyReport:
    verified: list[uuid.UUID] = field(default_factory=list)  # improved
    replayed: int = 0
    waiting: int = 0  # not approved yet, upkeep owed, Meko indexing, or past this run's replays


def session_key(household_id: uuid.UUID) -> str:
    return f"kako-gaps-{household_id}"


async def _conversation(conn: AsyncConnection, meko: Meko, household_id: uuid.UUID) -> str:
    household = (
        await conn.execute(
            select(HOUSEHOLD.c.name, HOUSEHOLD.c.meko_datapack_id).where(
                HOUSEHOLD.c.id == household_id
            )
        )
    ).first()
    if household is None:
        raise GapError("no such household")
    if household.meko_datapack_id is not None and meko.datapack_id != household.meko_datapack_id:
        raise GapError("Meko isn't on this household's datapack")
    return await meko.create_conversation(
        agent_id=AGENT,
        title=f"Kako's Context Gaps for the {household.name}",
        session_key=session_key(household_id),
    )


async def collect_gaps(engine: AsyncEngine, meko: Meko, household_id: uuid.UUID) -> list[uuid.UUID]:
    """Meko's weak searches on the household's datapack, kept as open gaps (new ones only)."""
    async with engine.connect() as conn:
        conversation_id = await _conversation(conn, meko, household_id)
    found = [
        s
        for band in ("low", "mid")
        for s in await meko.logged_searches(conversation_id, agent_id=AGENT, band=band)
        if worth_asking(s)
    ]
    made: list[uuid.UUID] = []
    async with engine.begin() as conn:
        for search in found:
            gap_id = uuid.uuid4()
            done = await conn.execute(
                insert(GAP)
                .values(
                    id=gap_id,
                    household_id=household_id,
                    meko_log_id=search.log_id,
                    query=search.query,
                    band_before=search.band,
                    score_before=Decimal(str(search.score or 0)).quantize(Decimal("0.001")),
                    reason=reason_of(search),
                    question=question(search),
                    status="open",
                )
                .on_conflict_do_nothing(index_elements=["meko_log_id"])
                .returning(GAP.c.id)
            )
            if done.first() is not None:
                made.append(gap_id)
    return made


def _gap(row: object) -> Gap:
    return Gap(**{name: getattr(row, name) for name in Gap.__dataclass_fields__})


async def list_gaps(
    conn: AsyncConnection, household_id: uuid.UUID, *, status: Status | None = None
) -> list[Gap]:
    query = select(*(GAP.c[name] for name in Gap.__dataclass_fields__)).where(
        GAP.c.household_id == household_id
    )
    if status is not None:
        query = query.where(GAP.c.status == status)
    rows = await conn.execute(query.order_by(GAP.c.band_before, GAP.c.score_before, GAP.c.id))
    return [_gap(r) for r in rows]


async def _locked(conn: AsyncConnection, household_id: uuid.UUID, gap_id: uuid.UUID) -> Gap:
    row = (
        await conn.execute(
            select(*(GAP.c[name] for name in Gap.__dataclass_fields__))
            .where(GAP.c.id == gap_id, GAP.c.household_id == household_id)
            .with_for_update()
        )
    ).first()
    if row is None:
        raise GapError("no such gap in this household")
    return _gap(row)


async def answer_gap(
    conn: AsyncConnection, household_id: uuid.UUID, gap_id: uuid.UUID, proposal_id: uuid.UUID
) -> Gap:
    """Tie the gap to the proposal that answers it: one of the household's, pending or approved,
    that writes a fact (Meko upkeep turns each fact into a memory the search can find)."""
    gap = await _locked(conn, household_id, gap_id)
    if gap.status not in ("open", "asked", "answered"):
        raise GapError(f"the gap is {gap.status}")
    proposal = (
        await conn.execute(
            select(PROPOSAL.c.kind, PROPOSAL.c.status).where(
                PROPOSAL.c.id == proposal_id, PROPOSAL.c.household_id == household_id
            )
        )
    ).first()
    if proposal is None:
        raise GapError("no such proposal in this household")
    if proposal.kind not in FACT_KINDS:
        raise GapError("an answer is a proposal that writes a fact")
    if proposal.status not in ("pending", "approved"):
        raise GapError(f"the proposal is {proposal.status}")
    await conn.execute(
        update(GAP)
        .where(GAP.c.id == gap_id)
        .values(proposal_id=proposal_id, status="answered", verify_outcome=None, score_after=None)
    )
    return await _locked(conn, household_id, gap_id)


async def dismiss_gap(
    conn: AsyncConnection, household_id: uuid.UUID, gap_id: uuid.UUID, person_id: uuid.UUID
) -> Gap:
    """An adult of the household says the gap isn't worth answering."""
    adult = (
        await conn.execute(
            select(PERSON.c.id).where(
                PERSON.c.id == person_id,
                PERSON.c.household_id == household_id,
                PERSON.c.role == "adult",
            )
        )
    ).first()
    if adult is None:
        raise GapError("only an adult of the household dismisses a gap")
    gap = await _locked(conn, household_id, gap_id)
    if gap.status == "verified":
        raise GapError("the gap is verified already")
    await conn.execute(update(GAP).where(GAP.c.id == gap_id).values(status="dismissed"))
    return await _locked(conn, household_id, gap_id)


async def _ready(conn: AsyncConnection, proposal_id: uuid.UUID) -> bool:
    """The answer is approved, and every fact it wrote has Kako's own memory in Meko."""
    status = (
        await conn.execute(select(PROPOSAL.c.status).where(PROPOSAL.c.id == proposal_id))
    ).scalar_one()
    if status != "approved":
        return False
    facts = list(
        (await conn.execute(select(FACT.c.id).where(FACT.c.proposal_id == proposal_id))).scalars()
    )
    if not facts:
        return False
    linked = set(
        (
            await conn.execute(
                select(MEKO_LINK.c.kako_id).where(
                    MEKO_LINK.c.kako_table == "fact",
                    MEKO_LINK.c.kako_id.in_(facts),
                    MEKO_LINK.c.meko_kind == "memory",
                    MEKO_LINK.c.text.is_not(None),
                )
            )
        ).scalars()
    )
    return linked == set(facts)


async def waiting_replays(conn: AsyncConnection, household_id: uuid.UUID) -> int:
    """How many answered gaps have no outcome yet."""
    rows = await conn.execute(
        select(GAP.c.id).where(
            GAP.c.household_id == household_id,
            GAP.c.status == "answered",
            GAP.c.verify_outcome.is_(None),
        )
    )
    return len(list(rows))


async def verify_gaps(
    engine: AsyncEngine,
    meko: Meko,
    household_id: uuid.UUID,
    *,
    gap_id: uuid.UUID | None = None,
) -> VerifyReport:
    """Replay the answered searches that are ready: each with no outcome yet, or `gap_id` again."""
    report = VerifyReport()
    async with engine.connect() as conn:
        query = select(GAP.c.id, GAP.c.meko_log_id, GAP.c.proposal_id).where(
            GAP.c.household_id == household_id, GAP.c.status == "answered"
        )
        if gap_id is None:
            query = query.where(GAP.c.verify_outcome.is_(None))
        else:
            query = query.where(GAP.c.id == gap_id)
        answered = list(await conn.execute(query.order_by(GAP.c.id)))
        ready = [g for g in answered if await _ready(conn, g.proposal_id)]
        report.waiting = len(answered) - len(ready)
        if not ready:
            return report
        conversation_id = await _conversation(conn, meko, household_id)
    for n, gap in enumerate(ready):
        if n >= MAX_REPLAYS:
            report.waiting += len(ready) - n
            break
        replay = await meko.replay_search(conversation_id, gap.meko_log_id, agent_id=AGENT)
        report.replayed += 1
        if replay.indexing:
            report.waiting += 1
            continue
        improved = replay.outcome == "improved"
        after = replay.score_after
        async with engine.begin() as conn:
            await conn.execute(
                update(GAP)
                .where(GAP.c.id == gap.id)
                .values(
                    verify_outcome=replay.outcome,
                    score_after=(
                        Decimal(str(after)).quantize(Decimal("0.001"))
                        if after is not None
                        else None
                    ),
                    status="verified" if improved else "answered",
                )
            )
        if improved:
            report.verified.append(gap.id)
    return report


VERIFY_CALLS: Final = 1 + MAX_REPLAYS  # the conversation, then the replays


async def collect_with(
    engine: AsyncEngine, settings: Settings, household_id: uuid.UUID
) -> list[uuid.UUID]:
    """`collect_gaps` on the configured Meko, every call counted in `meko_call`."""
    from kako.db.meko_log import DbCallLog
    from kako.meko.mcp import open_meko

    async with open_meko(settings, DbCallLog(engine), max_calls=COLLECT_CALLS) as meko:
        return await collect_gaps(engine, meko, household_id)


async def verify_with(
    engine: AsyncEngine,
    settings: Settings,
    household_id: uuid.UUID,
    *,
    gap_id: uuid.UUID | None = None,
) -> VerifyReport:
    """`verify_gaps` on the configured Meko, every call counted in `meko_call`."""
    from kako.db.meko_log import DbCallLog
    from kako.meko.mcp import open_meko

    async with open_meko(settings, DbCallLog(engine), max_calls=VERIFY_CALLS) as meko:
        return await verify_gaps(engine, meko, household_id, gap_id=gap_id)
