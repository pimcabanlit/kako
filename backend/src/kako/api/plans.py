"""The plan API: the household's plans, and one plan with its "why", for the plan screen.

- `GET /api/v1/plans` lists the household's plans, the newest version first.
- `GET /api/v1/plans/{id}` is one plan: its options and their allocations; for each option, why
  (the figures it cites, each with its formula in words and the facts and figures it was built
  from, down to the facts; the facts, with where each came from and who approved it; the
  decisions, with the options they rejected; the memories and documents Meko gave; the household's
  own words) and what the number check found; how a conflict between specialists ended; the turn
  that proposed it, its Meko calls and the trace link on Meko Cloud; and what changed against the
  household's last plan (or, for the first, the run it last decided on), with the decisions to
  revisit.
- `GET /api/v1/plans/{id}/compare` sets each of the plan's options beside today's plan (the turn's
  own snapshot): what each reaches and what each changes, and its months one by one
  (`planning.compare`; docs/data-model.md, "Before and after an option"). 409 when the turn's
  snapshot can't be taken again exactly.

Read-only, and only the household's rows (`db.plan_read`). Every value is the engine's or a fact's,
written out by code. Kako has no sign-in yet: the app answers only on loopback (see `api.app`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from kako.agents.shown import LOCAL_PREFIX
from kako.api.sessions import _household, _services
from kako.db.compare_read import NotComparable, read_compare
from kako.db.plan_read import list_plans, read_plan

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PlanSummaryOut(_Out):
    id: uuid.UUID
    version: int
    status: str  # proposed, accepted, replaced
    session_id: uuid.UUID
    session_title: str
    created_at: datetime
    as_of: date
    recommended_option: str | None
    options: int


class FigureWhyOut(_Out):
    id: uuid.UUID
    title: str
    value: str
    flag: str | None
    formula: str
    formula_words: str
    what_if: str | None
    facts: list[uuid.UUID]
    inputs: list[uuid.UUID]


class FactWhyOut(_Out):
    id: uuid.UUID
    title: str
    value: str
    valid_from: date
    valid_to: date | None
    status: str
    source: str
    shared: str | None
    replaced: str | None


class RejectedOptionOut(_Out):
    label: str
    reason: str


class DecisionWhyOut(_Out):
    id: uuid.UUID
    question: str
    chosen: str
    reasoning: str
    session_title: str
    on: date
    status: str
    rejected: list[RejectedOptionOut]


class MemoryWhyOut(_Out):
    kind: str
    source_id: str
    quote: str | None
    fact_id: uuid.UUID | None


class WordsOut(_Out):
    quote: str
    said_by: str | None


class WhyOut(_Out):
    figures: list[uuid.UUID]
    facts: list[uuid.UUID]
    decisions: list[DecisionWhyOut]
    memories: list[MemoryWhyOut]
    words: list[WordsOut]


class AllocationOut(_Out):
    recommendation_id: uuid.UUID
    entity_id: uuid.UUID | None
    name: str
    area: str
    specialist: str
    centavos: int | None
    shown: str


class CheckedNumberOut(_Out):
    text: str
    matched: str | None


class CheckOut(_Out):
    text: str
    result: str
    numbers: list[CheckedNumberOut]


class OptionOut(_Out):
    label: str
    recommended: bool
    summary: str
    specialists: list[str]
    allocations: list[AllocationOut]
    why: WhyOut
    checks: list[CheckOut]


class ReconciliationOut(_Out):
    kind: str
    specialists: list[str]
    resolution: str
    rejected: str | None
    attempts: int


class MekoCallOut(_Out):
    tool: str
    agent_id: str
    ms: int | None
    results: int | None
    outcome: str
    at: datetime


class TurnOut(_Out):
    session_id: uuid.UUID
    seed: str | None
    message: str | None
    said_by: str | None
    kept_at: datetime | None
    in_meko: bool
    trace_url: str | None
    meko_calls: list[MekoCallOut]


class MovedOut(_Out):
    title: str
    before: str
    after: str
    headline: bool


class ChangedFactOut(_Out):
    label: str
    title: str
    before: str | None
    after: str | None
    from_day: str | None


class RevisitOut(_Out):
    decision_id: uuid.UUID
    question: str
    chosen: str
    session_title: str
    decided_on: date
    because: list[ChangedFactOut]


class ChangedOut(BaseModel):
    since: str
    since_plan: uuid.UUID | None
    figures: list[MovedOut]
    facts: list[ChangedFactOut]
    revisit: list[RevisitOut]


class PlanOut(BaseModel):
    plan: PlanSummaryOut
    summary: str
    options: list[OptionOut]
    reconciliations: list[ReconciliationOut]
    turn: TurnOut
    changed: ChangedOut | None
    figures: dict[str, FigureWhyOut]
    facts: dict[str, FactWhyOut]


@router.get("", response_model=list[PlanSummaryOut])
async def read_plans(
    request: Request, household_id: uuid.UUID | None = None
) -> list[PlanSummaryOut]:
    """The household's plans, the newest version first."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        rows = await list_plans(conn, household)
    return [PlanSummaryOut.model_validate(r) for r in rows]


@router.get("/{plan_id}", response_model=PlanOut)
async def read_one_plan(
    plan_id: uuid.UUID, request: Request, household_id: uuid.UUID | None = None
) -> PlanOut:
    """One plan with its why and what changed."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        view = await read_plan(conn, household, plan_id)
    if view is None:
        raise HTTPException(404, "no such plan")
    conversation = view.turn.conversation_id
    in_meko = not conversation.startswith(LOCAL_PREFIX)
    turn = TurnOut(
        session_id=view.turn.session_id,
        seed=view.turn.seed,
        message=view.turn.message,
        said_by=view.turn.said_by,
        kept_at=view.turn.kept_at,
        in_meko=in_meko,
        trace_url=services.settings.meko_trace_url(conversation) if in_meko else None,
        meko_calls=[MekoCallOut.model_validate(c) for c in view.turn.meko_calls],
    )
    changed = None
    if view.changed is not None:
        c = view.changed
        changed = ChangedOut(
            since=c.since,
            since_plan=c.since_plan,
            figures=[MovedOut.model_validate(f) for f in c.changes.figures],
            facts=[ChangedFactOut.model_validate(f) for f in c.changes.facts],
            revisit=[RevisitOut.model_validate(r) for r in c.revisit],
        )
    return PlanOut(
        plan=PlanSummaryOut.model_validate(view.plan),
        summary=view.summary,
        options=[OptionOut.model_validate(o) for o in view.options],
        reconciliations=[ReconciliationOut.model_validate(r) for r in view.reconciliations],
        turn=turn,
        changed=changed,
        figures={str(k): FigureWhyOut.model_validate(v) for k, v in view.figures.items()},
        facts={str(k): FactWhyOut.model_validate(v) for k, v in view.facts.items()},
    )


# --- Before and after ----------------------------------------------------------------------------


class CellOut(_Out):
    value: str
    note: str | None
    change: str | None
    direction: str  # better, worse, same, none


class CompareRowOut(_Out):
    key: str
    kind: str  # debt_paid, debt_interest, interest_total, emergency_fund, goal_reached, unplanned
    label: str
    on_card: bool
    before: CellOut
    options: list[CellOut]


class OptionHeadOut(_Out):
    label: str
    each_month: str


class MonthRowOut(_Out):
    month: int
    on: date
    payment: str
    interest: str
    principal: str
    left: str
    fill: float
    before_left: str | None
    before_fill: float | None
    rolled_in: str | None
    rolled_from: str | None


class DebtMonthsOut(_Out):
    name: str
    paid_off: date | None
    change: str | None
    direction: str
    rows: list[MonthRowOut]
    paid_total: str
    interest_total: str
    principal_total: str
    closing: str
    before_closing: str | None


class FundMonthOut(_Out):
    month: int
    on: date
    added: str
    balance: str
    to_go: str | None
    fill: float


class FundOut(_Out):
    name: str
    target: str
    reached_on: date
    closing: str
    before_closing: str
    rows: list[FundMonthOut]


class OptionMonthsOut(_Out):
    label: str
    debts: list[DebtMonthsOut]
    fund: FundOut | None


class CompareOut(_Out):
    plan_id: uuid.UUID
    as_of: date
    baseline: str
    each_month: str
    options: list[OptionHeadOut]
    rows: list[CompareRowOut]
    months: list[OptionMonthsOut]


@router.get("/{plan_id}/compare", response_model=CompareOut)
async def compare_plan(
    plan_id: uuid.UUID, request: Request, household_id: uuid.UUID | None = None
) -> CompareOut:
    """Each of the plan's options beside today's plan, every number the engine's."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        try:
            found = await read_compare(conn, household, plan_id)
        except NotComparable as exc:
            raise HTTPException(409, f"These options can't be compared: {exc}.") from None
    if found is None:
        raise HTTPException(404, "no such plan")
    return CompareOut.model_validate(found)
