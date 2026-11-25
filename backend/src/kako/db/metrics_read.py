"""What the metrics page reads from Postgres: only the household's rows, and the call counter.

- Each turn's model calls, tokens, cost and seconds (`llm_call`, by session and turn) and its
  brief's size (`session_turn.shown`), in three groups: the household's own sessions, and the
  agent test set's sessions for each architecture (told apart by their titles).
- The number check (`number_check`): each text's last check passed or failed; a `regenerated` row
  is a first try that was sent back.
- Dreaming's runs (`dream_run`) and Context Gaps (`context_gap`) with their before and after scores.
- Meko calls by allowance (`meko_call`), local and cloud. The counter is this environment's (one
  database), not the account's.

The figures are worked out in `kako.metrics.turns` (pure).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal, cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.models import (
    ContextGap,
    DreamRun,
    LlmCall,
    MekoCall,
    NumberCheck,
    Session,
    SessionTurn,
)
from kako.evals.questions import architecture_of
from kako.meko.quota import FREE_ALLOWANCE, ceiling_for, tools_counted_with
from kako.metrics.turns import Call, TurnFigures, turn_figures

SESSION = cast(Table, Session.__table__)
TURN = cast(Table, SessionTurn.__table__)
LLM_CALL = cast(Table, LlmCall.__table__)
MEKO_CALL = cast(Table, MekoCall.__table__)
NUMBER_CHECK = cast(Table, NumberCheck.__table__)
DREAM_RUN = cast(Table, DreamRun.__table__)
GAP = cast(Table, ContextGap.__table__)

Group = Literal["household", "specialists", "single"]
GROUPS: Final[tuple[Group, ...]] = ("household", "specialists", "single")


def group_of(title: str) -> Group:
    architecture = architecture_of(title)
    if architecture == "specialists":
        return "specialists"
    if architecture == "single":
        return "single"
    return "household"


@dataclass(frozen=True)
class Checks:
    passed: int
    failed: int
    regenerated: int  # first tries sent back with the numbers named


@dataclass(frozen=True)
class DreamRuns:
    done: int
    failed: int
    waiting: int  # queued or running
    proposals: int  # what the done runs proposed, as their counts say


@dataclass(frozen=True)
class GapRow:
    query: str
    band_before: str
    score_before: Decimal
    status: str
    verify_outcome: str | None
    score_after: Decimal | None


@dataclass(frozen=True)
class Allowance:
    name: str  # the capped tool its calls count against
    tools: tuple[str, ...]  # every tool counted with it
    free: int  # the Free tier's lifetime allowance
    local_used: int
    cloud_used: int
    cloud_ceiling: int  # this environment's ceiling on Meko Cloud, never above `free`

    @property
    def cloud_left(self) -> int:
        return max(self.cloud_ceiling - self.cloud_used, 0)


@dataclass(frozen=True)
class StoredMetrics:
    turns: dict[Group, list[TurnFigures]]
    checks: dict[Group, Checks]
    dreams: DreamRuns
    gaps: list[GapRow]
    allowances: list[Allowance]


async def _sessions(conn: AsyncConnection, household_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = await conn.execute(
        select(SESSION.c.id, SESSION.c.title).where(SESSION.c.household_id == household_id)
    )
    return {r.id: r.title for r in rows}


def _brief_tokens(shown: Any) -> int | None:
    cost = shown.get("cost") if isinstance(shown, dict) else None
    value = cost.get("brief_tokens") if isinstance(cost, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def read_turns(
    conn: AsyncConnection, household_id: uuid.UUID
) -> dict[Group, list[TurnFigures]]:
    """Every kept turn of the household's sessions with its figures, oldest first, by group. A turn
    is kept once answered (`session_turn`); its calls include retries and send-backs."""
    sessions = await _sessions(conn, household_id)
    turns: dict[Group, list[TurnFigures]] = {g: [] for g in GROUPS}
    if not sessions:
        return turns
    kept = (
        await conn.execute(
            select(TURN.c.session_id, TURN.c.meko_turn_seed, TURN.c.shown)
            .where(TURN.c.session_id.in_(sessions))
            .order_by(TURN.c.created_at, TURN.c.id)
        )
    ).all()
    calls: dict[tuple[uuid.UUID, str], list[Call]] = defaultdict(list)
    rows = await conn.execute(
        select(
            LLM_CALL.c.session_id,
            LLM_CALL.c.meko_turn_seed,
            LLM_CALL.c.agent,
            LLM_CALL.c.latency_ms,
            LLM_CALL.c.input_tokens,
            LLM_CALL.c.output_tokens,
            LLM_CALL.c.cached_tokens,
            LLM_CALL.c.cost_usd,
            LLM_CALL.c.recorded_replay,
        )
        .where(LLM_CALL.c.session_id.in_(sessions), LLM_CALL.c.meko_turn_seed.is_not(None))
        .order_by(LLM_CALL.c.created_at, LLM_CALL.c.id)
    )
    for r in rows:
        calls[(r.session_id, r.meko_turn_seed)].append(
            Call(
                agent=r.agent,
                latency_ms=r.latency_ms,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                cached_tokens=r.cached_tokens,
                cost_usd=r.cost_usd,
                replayed=r.recorded_replay,
            )
        )
    for turn in kept:
        title = sessions[turn.session_id]
        turns[group_of(title)].append(
            turn_figures(
                turn.session_id,
                turn.meko_turn_seed,
                title,
                calls.get((turn.session_id, turn.meko_turn_seed), []),
                _brief_tokens(turn.shown),
            )
        )
    return turns


async def read_checks(conn: AsyncConnection, household_id: uuid.UUID) -> dict[Group, Checks]:
    """The number check's results on the household's sessions, by group."""
    sessions = await _sessions(conn, household_id)
    counts: dict[Group, dict[str, int]] = {g: defaultdict(int) for g in GROUPS}
    if sessions:
        rows = await conn.execute(
            select(NUMBER_CHECK.c.session_id, NUMBER_CHECK.c.result, func.count())
            .where(NUMBER_CHECK.c.session_id.in_(sessions))
            .group_by(NUMBER_CHECK.c.session_id, NUMBER_CHECK.c.result)
        )
        for session_id, result, count in rows:
            counts[group_of(sessions[session_id])][result] += count
    return {g: Checks(c["pass"], c["fail"], c["regenerated"]) for g, c in counts.items()}


def _proposed(counts: Any) -> int:
    """What a run proposed, as its counts say: the changes it found (`proposals`, by kind), the
    patterns code found (`patterns`) and the sharing it offered (`promotions`)."""
    if not isinstance(counts, dict):
        return 0
    kinds = counts.get("proposals")
    found = (
        sum(n for n in kinds.values() if isinstance(n, int) and not isinstance(n, bool))
        if isinstance(kinds, dict)
        else 0
    )
    listed = sum(len(v) for k in ("patterns", "promotions") if isinstance(v := counts.get(k), list))
    return found + listed


async def read_dreams(conn: AsyncConnection, household_id: uuid.UUID) -> DreamRuns:
    rows = (
        await conn.execute(
            select(DREAM_RUN.c.status, DREAM_RUN.c.counts)
            .join(SESSION, SESSION.c.id == DREAM_RUN.c.session_id)
            .where(SESSION.c.household_id == household_id)
        )
    ).all()
    return DreamRuns(
        done=sum(r.status == "done" for r in rows),
        failed=sum(r.status == "failed" for r in rows),
        waiting=sum(r.status in ("queued", "running") for r in rows),
        proposals=sum(_proposed(r.counts) for r in rows if r.status == "done"),
    )


async def read_gaps(conn: AsyncConnection, household_id: uuid.UUID) -> list[GapRow]:
    """Every gap, the ones replayed first, then the weakest score before."""
    rows = await conn.execute(
        select(
            GAP.c.query,
            GAP.c.band_before,
            GAP.c.score_before,
            GAP.c.status,
            GAP.c.verify_outcome,
            GAP.c.score_after,
        )
        .where(GAP.c.household_id == household_id)
        .order_by(GAP.c.score_after.is_(None), GAP.c.score_before, GAP.c.query)
    )
    return [GapRow(**r._mapping) for r in rows]


async def read_allowances(conn: AsyncConnection, cloud_ceiling: int) -> list[Allowance]:
    """Each Free-tier allowance: the calls made against it here, on local Meko and on Meko Cloud
    (refused calls weren't sent, so they don't count), and what is left under the ceiling."""
    rows = await conn.execute(
        select(MEKO_CALL.c.target, MEKO_CALL.c.tool, func.count())
        .where(MEKO_CALL.c.outcome != "refused")
        .group_by(MEKO_CALL.c.target, MEKO_CALL.c.tool)
    )
    used: dict[tuple[str, str], int] = {(t, tool): n for t, tool, n in rows}
    allowances = []
    for name in sorted(FREE_ALLOWANCE):
        tools = tools_counted_with(name)
        ceiling = ceiling_for("cloud", name, cloud_ceiling)
        allowances.append(
            Allowance(
                name=name,
                tools=tools,
                free=FREE_ALLOWANCE[name],
                local_used=sum(used.get(("local", t), 0) for t in tools),
                cloud_used=sum(used.get(("cloud", t), 0) for t in tools),
                cloud_ceiling=ceiling if ceiling is not None else 0,
            )
        )
    return allowances


async def read_stored_metrics(
    conn: AsyncConnection, household_id: uuid.UUID, *, cloud_ceiling: int
) -> StoredMetrics:
    return StoredMetrics(
        turns=await read_turns(conn, household_id),
        checks=await read_checks(conn, household_id),
        dreams=await read_dreams(conn, household_id),
        gaps=await read_gaps(conn, household_id),
        allowances=await read_allowances(conn, cloud_ceiling),
    )
