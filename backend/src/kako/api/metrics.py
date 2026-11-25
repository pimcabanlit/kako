"""The metrics API: what Kako measured, every figure worked out in code from stored rows and saved
results. Read only, and only the household's rows (the Meko call counter is this environment's).

- `GET /api/v1/metrics`: each turn's model calls, tokens, cost and seconds (average and worst case)
  and its brief's size, for the household's sessions and for the agent test set's, by architecture;
  the number check; the agent test set against the single-agent baseline; the learned preference's
  effect; dreaming; Context Gaps' before and after scores; and the Meko calls each Free-tier
  allowance has left. A saved result that can't be read is reported on its own, with the rest shown.
- `GET /api/v1/metrics/meko`: Meko's own `datapack_metrics` for the household's datapack (its
  context size, efficiency and relevance), read live: one call, and a conversation for it once per
  process.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Literal, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import Table, select

from kako.api.sessions import Services, _household, _services
from kako.db.meko_log import DbCallLog
from kako.db.metrics_read import (
    GROUPS,
    Allowance,
    Checks,
    DreamRuns,
    GapRow,
    Group,
    read_stored_metrics,
    read_turns,
)
from kako.db.models import Household
from kako.evals.preference import EffectSide, PreferenceEffect, read_preference_effect
from kako.evals.results import (
    DreamingRun,
    ResultsError,
    TestSetRun,
    read_dreaming_run,
    read_test_set_run,
)
from kako.health import safe_error
from kako.meko.adapter import DatapackMetrics
from kako.meko.client import MekoError
from kako.metrics.turns import Spread, TurnFigures, dollars, seconds, share, spread, whole

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

HOUSEHOLD = cast(Table, Household.__table__)
AGENT: Final = "kako:metrics"
MEKO_CALLS: Final = 2  # the conversation (once per process) and datapack_metrics


class SpreadOut(BaseModel):
    """A measure's average over the turns and its worst case, as shown (decimal strings)."""

    average: str
    worst: str
    worst_session_id: uuid.UUID
    worst_seed: str
    worst_title: str


class ChecksOut(BaseModel):
    texts: int  # the texts the household read: each one's last check
    passed: int
    failed: int
    regenerated: int  # first tries sent back with the numbers named
    pass_pct: str | None


class TurnGroupOut(BaseModel):
    group: Group
    turns: int
    replayed: int  # turns replayed from a recording: their cost and seconds are the recording's
    model_calls: SpreadOut | None
    tokens: SpreadOut | None  # input and output
    cached_pct: str | None  # the share of input tokens served from the cache
    cost_usd: SpreadOut | None
    seconds: SpreadOut | None
    brief_tokens: SpreadOut | None
    brief_turns: int  # turns that kept their brief's size
    checks: ChecksOut


class TestSetOut(BaseModel):
    __test__ = False  # not a pytest test class

    architecture: str
    mode: str
    run_at: datetime
    deployments: dict[str, str]
    questions: int
    answered: int
    score_pct: str
    checks_passed: int
    checks_total: int
    model_calls: int
    tokens: int
    cost_usd: str
    meko_calls: int


class TestSetsOut(BaseModel):
    __test__ = False

    specialists: TestSetOut | None
    single: TestSetOut | None
    error: str | None = None


class EffectSideOut(BaseModel):
    run_at: datetime
    mode: str
    model_calls: int
    cost_usd: str
    score_pct: str
    behaviour_pct: str  # leaving out the check that cites the preference


class EffectQuestionOut(BaseModel):
    id: str
    message: str | None
    score_with_pct: str
    score_without_pct: str
    behaviour_with_pct: str
    behaviour_without_pct: str
    cited_with: bool | None
    cited_without: bool | None


class PreferenceOut(BaseModel):
    measured: bool
    preference: str | None = None
    with_side: EffectSideOut | None = None
    without_side: EffectSideOut | None = None
    questions: list[EffectQuestionOut] = []
    error: str | None = None


class DreamingOut(BaseModel):
    runs_done: int
    runs_failed: int
    runs_waiting: int
    proposals: int
    eval_at: datetime | None = None
    eval_mode: str | None = None
    expected: int | None = None
    found: int | None = None
    score_pct: str | None = None
    wrong: int | None = None
    unquoted: int | None = None
    passed: bool | None = None
    error: str | None = None


class GapOut(BaseModel):
    query: str
    band_before: str
    score_before: str
    status: str
    verify_outcome: str | None
    score_after: str | None


class GapsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    replayed: int
    improved: int
    gaps: list[GapOut]


class AllowanceOut(BaseModel):
    name: str
    tools: list[str]
    free: int
    local_used: int
    cloud_used: int
    cloud_ceiling: int
    cloud_left: int


class MekoCallsOut(BaseModel):
    target: Literal["local", "cloud"]  # where this environment's Meko calls go now
    allowances: list[AllowanceOut]


class MetricsOut(BaseModel):
    measured_at: datetime
    brief_budget: int  # KAKO_BRIEF_TOKEN_BUDGET now
    turns: list[TurnGroupOut]
    test_set: TestSetsOut
    preference: PreferenceOut
    dreaming: DreamingOut
    gaps: GapsOut
    meko_calls: MekoCallsOut


def _pct(ratio: Decimal) -> str:
    """A 0-to-1 score as a percentage to one decimal, half up."""
    return str((ratio * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _spread(
    turns: list[TurnFigures],
    measure: Callable[[TurnFigures], Decimal | int | None],
    shown: Callable[[Decimal], str],
) -> SpreadOut | None:
    found: Spread | None = spread(turns, measure)
    if found is None:
        return None
    return SpreadOut(
        average=shown(found.average),
        worst=shown(found.worst),
        worst_session_id=found.worst_session_id,
        worst_seed=found.worst_seed,
        worst_title=found.worst_title,
    )


def _checks(checks: Checks) -> ChecksOut:
    texts = checks.passed + checks.failed
    pct = share(checks.passed, texts)
    return ChecksOut(
        texts=texts,
        passed=checks.passed,
        failed=checks.failed,
        regenerated=checks.regenerated,
        pass_pct=str(pct) if pct is not None else None,
    )


def _group(group: Group, turns: list[TurnFigures], checks: Checks) -> TurnGroupOut:
    cached = share(sum(t.cached_tokens for t in turns), sum(t.input_tokens for t in turns))
    return TurnGroupOut(
        group=group,
        turns=len(turns),
        replayed=sum(t.replayed for t in turns),
        model_calls=_spread(turns, lambda t: t.model_calls, lambda v: f"{v:.1f}"),
        tokens=_spread(turns, lambda t: t.tokens, lambda v: str(whole(v))),
        cached_pct=str(cached) if cached is not None else None,
        cost_usd=_spread(turns, lambda t: t.cost_usd, lambda v: str(dollars(v))),
        seconds=_spread(turns, lambda t: t.model_ms, lambda v: str(seconds(v))),
        brief_tokens=_spread(turns, lambda t: t.brief_tokens, lambda v: str(whole(v))),
        brief_turns=sum(t.brief_tokens is not None for t in turns),
        checks=_checks(checks),
    )


def _test_set(run: TestSetRun | None) -> TestSetOut | None:
    if run is None:
        return None
    return TestSetOut(
        architecture=run.architecture,
        mode=run.mode,
        run_at=run.run_at,
        deployments=run.deployments,
        questions=run.questions,
        answered=run.answered,
        score_pct=_pct(run.score),
        checks_passed=run.checks_passed,
        checks_total=run.checks_total,
        model_calls=run.model_calls,
        tokens=run.input_tokens + run.output_tokens,
        cost_usd=str(run.cost_usd),
        meko_calls=run.meko_calls,
    )


def _test_sets() -> TestSetsOut:
    try:
        return TestSetsOut(
            specialists=_test_set(read_test_set_run("specialists")),
            single=_test_set(read_test_set_run("single")),
        )
    except ResultsError as exc:
        return TestSetsOut(specialists=None, single=None, error=str(exc))


def _preference(messages: dict[str, str]) -> PreferenceOut:
    try:
        effect: PreferenceEffect | None = read_preference_effect()
    except ResultsError as exc:
        return PreferenceOut(measured=False, error=str(exc))
    if effect is None:
        return PreferenceOut(measured=False)

    def side(s: EffectSide) -> EffectSideOut:
        return EffectSideOut(
            run_at=s.run_at,
            mode=s.mode,
            model_calls=s.model_calls,
            cost_usd=str(s.cost_usd),
            score_pct=_pct(s.score),
            behaviour_pct=_pct(s.behaviour),
        )

    return PreferenceOut(
        measured=True,
        preference=effect.preference,
        with_side=side(effect.with_side),
        without_side=side(effect.without_side),
        questions=[
            EffectQuestionOut(
                id=q.id,
                message=messages.get(q.id),
                score_with_pct=_pct(q.score_with),
                score_without_pct=_pct(q.score_without),
                behaviour_with_pct=_pct(q.behaviour_with),
                behaviour_without_pct=_pct(q.behaviour_without),
                cited_with=q.cited_with,
                cited_without=q.cited_without,
            )
            for q in effect.questions
        ],
    )


def _dreaming(runs: DreamRuns) -> DreamingOut:
    out = DreamingOut(
        runs_done=runs.done,
        runs_failed=runs.failed,
        runs_waiting=runs.waiting,
        proposals=runs.proposals,
    )
    try:
        saved: DreamingRun | None = read_dreaming_run()
    except ResultsError as exc:
        return out.model_copy(update={"error": str(exc)})
    if saved is None:
        return out
    return out.model_copy(
        update={
            "eval_at": saved.at,
            "eval_mode": saved.mode,
            "expected": saved.expected,
            "found": saved.found,
            "score_pct": _pct(saved.score),
            "wrong": saved.wrong,
            "unquoted": saved.unquoted,
            "passed": saved.passed,
        }
    )


def _gaps(rows: list[GapRow]) -> GapsOut:
    by_status: dict[str, int] = {}
    for g in rows:
        by_status[g.status] = by_status.get(g.status, 0) + 1
    return GapsOut(
        total=len(rows),
        by_status=by_status,
        replayed=sum(g.verify_outcome is not None for g in rows),
        improved=sum(g.verify_outcome == "improved" for g in rows),
        gaps=[
            GapOut(
                query=g.query,
                band_before=g.band_before,
                score_before=str(g.score_before),
                status=g.status,
                verify_outcome=g.verify_outcome,
                score_after=str(g.score_after) if g.score_after is not None else None,
            )
            for g in rows
        ],
    )


def _allowance(a: Allowance) -> AllowanceOut:
    return AllowanceOut(
        name=a.name,
        tools=list(a.tools),
        free=a.free,
        local_used=a.local_used,
        cloud_used=a.cloud_used,
        cloud_ceiling=a.cloud_ceiling,
        cloud_left=a.cloud_left,
    )


def _messages() -> dict[str, str]:
    """The test set's questions by id, for the preference's rows; empty if the set can't be read."""
    from kako.evals.questions import TestSetError, read_test_set

    try:
        return {q.id: q.message for q in read_test_set()}
    except TestSetError:
        return {}


@router.get("", response_model=MetricsOut)
async def read_metrics(request: Request, household_id: uuid.UUID | None = None) -> MetricsOut:
    """What Kako measured, from stored rows and saved results (no Meko call)."""
    services: Services = _services(request)
    household, _ = await _household(services.engine, household_id)
    settings = services.settings
    async with services.engine.connect() as conn:
        stored = await read_stored_metrics(
            conn, household, cloud_ceiling=settings.meko_cloud_ceiling
        )
    return MetricsOut(
        measured_at=datetime.now(UTC),
        brief_budget=settings.brief_token_budget,
        turns=[_group(g, stored.turns[g], stored.checks[g]) for g in GROUPS],
        test_set=_test_sets(),
        preference=_preference(_messages()),
        dreaming=_dreaming(stored.dreams),
        gaps=_gaps(stored.gaps),
        meko_calls=MekoCallsOut(
            target=settings.meko_target,
            allowances=[_allowance(a) for a in stored.allowances],
        ),
    )


class HoldingOut(BaseModel):
    count: int
    tokens: int


class DatapackOut(BaseModel):
    """Meko's `datapack_metrics`, as Meko measured it."""

    target: Literal["local", "cloud"]
    datapack_id: str | None
    datapack_name: str | None
    days: int
    searches: int
    context_tokens: int
    knowledge: HoldingOut
    memories: HoldingOut
    conversations: HoldingOut
    tokens_sent: int | None
    tokens_saved: int | None
    saved_pct: int | None
    relevance_high: int | None
    relevance_mid: int | None
    relevance_low: int | None
    relevant_pct: int | None
    # The household's sessions' average brief against everything the datapack holds.
    brief_tokens: str | None
    brief_pct_of_context: str | None


def session_key(household_id: uuid.UUID) -> str:
    return f"kako-metrics-{household_id}"


@router.get("/meko", response_model=DatapackOut)
async def read_meko_metrics(request: Request, household_id: uuid.UUID | None = None) -> DatapackOut:
    """Meko's own metrics for the household's datapack, read now."""
    services: Services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        row = (
            await conn.execute(
                select(HOUSEHOLD.c.name, HOUSEHOLD.c.meko_datapack_id).where(
                    HOUSEHOLD.c.id == household
                )
            )
        ).one()
        briefs = spread((await read_turns(conn, household))["household"], lambda t: t.brief_tokens)
    key = session_key(household)
    try:
        async with services.open_meko(DbCallLog(services.engine), MEKO_CALLS) as meko:
            if meko is None:
                raise HTTPException(503, "Meko isn't configured")
            if row.meko_datapack_id is not None and meko.datapack_id != row.meko_datapack_id:
                raise HTTPException(409, "Meko isn't on this household's datapack")
            key = f"{meko.datapack_id or 'default'}:{session_key(household)}"
            conversation_id = services.conversations.get(key)
            if conversation_id is None:
                conversation_id = await meko.create_conversation(
                    agent_id=AGENT,
                    title=f"Kako's metrics for the {row.name}",
                    session_key=session_key(household),
                )
                services.conversations[key] = conversation_id
            found: DatapackMetrics = await meko.datapack_metrics(conversation_id, agent_id=AGENT)
    except MekoError as exc:
        services.conversations.pop(key, None)  # made again next time, in case it is gone
        raise HTTPException(502, f"Meko: {safe_error(exc)}") from None
    brief = whole(briefs.average) if briefs is not None else None
    brief_pct = share(brief, found.context_tokens) if brief is not None else None
    return DatapackOut(
        target=services.settings.meko_target,
        brief_tokens=str(brief) if brief is not None else None,
        brief_pct_of_context=str(brief_pct) if brief_pct is not None else None,
        datapack_id=found.datapack_id,
        datapack_name=found.datapack_name,
        days=found.days,
        searches=found.searches,
        context_tokens=found.context_tokens,
        knowledge=HoldingOut(**found.knowledge.__dict__),
        memories=HoldingOut(**found.memories.__dict__),
        conversations=HoldingOut(**found.conversations.__dict__),
        tokens_sent=found.tokens_sent,
        tokens_saved=found.tokens_saved,
        saved_pct=found.saved_pct,
        relevance_high=found.relevance_high,
        relevance_mid=found.relevance_mid,
        relevance_low=found.relevance_low,
        relevant_pct=found.relevant_pct,
    )
