"""The money API: where the household's money stands, on its date.

- `GET /api/v1/money`: four headline figures (total salary, what is free after expenses, months of
  emergency cover, net worth), where each peso of the pay goes (needs, wants, debt, savings), the
  month's plan line by line with what is left after each line, the plan before its last change, each
  debt with its month-by-month schedule, what the household owns and owes, the milestones ahead, big
  moments (13th-month pay, changes that take effect later) and the decisions in force.

Read-only, and only the household's rows (`db.money_read`, `planning.money`). Every number comes
from the engine or a fact, written out by code. Kako has no sign-in yet: the app answers only on
loopback (see `api.app`).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from kako.api.sessions import _household, _services
from kako.db.money_read import read_money

router = APIRouter(prefix="/api/v1", tags=["money"])


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TileOut(_Out):
    label: str
    value: str
    negative: bool


class SplitPartOut(_Out):
    key: str  # needs, wants, debt, savings, unplanned
    label: str
    amount: int  # centavos, for the chart
    text: str
    share: str


class SplitOut(_Out):
    total: str
    parts: list[SplitPartOut]
    over: str | None


class LineOut(_Out):
    kind: str  # in, need, want, debt, savings
    name: str
    amount: str | None
    left: str | None
    fill: float
    change: str | None


class PlanVersionOut(_Out):
    label: str
    on: date
    lines: list[LineOut]
    unplanned: str | None


class RowOut(_Out):
    month: int
    on: date
    owed: str
    interest: str
    payment: str
    principal: str
    left: str
    fill: float
    rolled_in: str | None
    rolled_from: str | None


class DebtOut(_Out):
    id: uuid.UUID
    name: str
    order: int | None
    balance: str
    since: date | None
    rate: str | None
    minimum: str | None
    extra: str | None
    paying: str | None
    payoff_on: date | None
    payoff_in: str | None
    interest_left: str | None
    why_not: str | None
    rows: list[RowOut]
    paid_total: str | None
    interest_total: str | None
    principal_total: str | None


class HoldingOut(_Out):
    name: str
    kind: str
    amount: str | None
    since: date | None


class StandingOut(_Out):
    owns: list[HoldingOut]
    owes: list[HoldingOut]
    owned: str | None
    owed: str | None
    net: str | None
    negative: bool


class MilestoneOut(_Out):
    kind: str  # emergency_fund, debt_paid, goal_reached
    on: date
    within: str
    name: str
    on_track: bool | None


class MomentOut(_Out):
    kind: str  # thirteenth_month, ahead
    on: date
    month_only: bool
    title: str
    value: str


class DecisionLineOut(_Out):
    id: uuid.UUID
    question: str
    chosen: str
    on: date
    session_title: str
    revisit: int


class MoneyOut(_Out):
    as_of: date
    tiles: list[TileOut]
    split: SplitOut | None
    plan: PlanVersionOut
    before: PlanVersionOut | None
    debts: list[DebtOut]
    standing: StandingOut
    milestones: list[MilestoneOut]
    moments: list[MomentOut]
    decisions: list[DecisionLineOut]


@router.get("/money", response_model=MoneyOut)
async def read_money_screen(request: Request, household_id: uuid.UUID | None = None) -> MoneyOut:
    """Where the household's money stands on its date, every number from the engine."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        found = await read_money(conn, household)
    return MoneyOut.model_validate(found)
