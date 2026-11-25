"""The money screen in words: where the household's money stands, from the engine.

Pure. Every number comes from `engine.money` (the plan line by line, the split, each debt's
schedule, what it owns and owes, the milestones) or the engine's figures, written out by code
(`agents.present`). Big moments add the 13th-month pay and the facts that take effect after the
household's date; `db.money_read` adds the decisions in force.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from kako.agents.present import day, fact_value, figure_value, money, months
from kako.engine.figures import Run
from kako.engine.inputs import Inputs
from kako.engine.money import (
    DebtSchedule,
    Holding,
    PlanLine,
    Split,
    line_changes,
    money_view,
    plan_before,
    plan_lines,
)
from kako.facts.model import EntityRow, FactRow
from kako.facts.snapshot import Snapshot, take_snapshot
from kako.planning.why import fact_title, flag_words


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    negative: bool


@dataclass(frozen=True)
class SplitPart:
    key: str  # needs, wants, debt, savings, unplanned
    label: str
    amount: int  # centavos, for the chart's arcs
    text: str
    share: str  # "60%"


@dataclass(frozen=True)
class SplitView:
    total: str
    parts: tuple[SplitPart, ...]  # the parts above zero
    over: str | None  # how far the plan goes over the pay


@dataclass(frozen=True)
class LineView:
    kind: str  # in, need, want, debt, savings
    name: str
    amount: str | None
    left: str | None
    fill: float  # what is left after it, as a share of the pay (0 to 1), for its bar
    change: str | None  # "was ₱4,000.00", "new"


@dataclass(frozen=True)
class PlanVersion:
    label: str  # "From Dec 1, 2026", "Before Dec 1, 2026"
    on: date
    lines: tuple[LineView, ...]
    unplanned: str | None


@dataclass(frozen=True)
class RowView:
    month: int
    on: date
    owed: str
    interest: str
    payment: str
    principal: str
    left: str
    fill: float  # what is left as a share of the balance today, for its bar
    rolled_in: str | None  # "₱12,550.00", when a paid-off debt's payment rolls in this month
    rolled_from: str | None  # the debt (or debts) paid off the month before: "Credit card"


@dataclass(frozen=True)
class DebtView:
    id: uuid.UUID
    name: str
    order: int | None
    balance: str
    since: date | None  # the statement's date
    rate: str | None  # "3% a month"
    minimum: str | None
    extra: str | None  # None when nothing extra
    paying: str | None  # minimum + extra
    payoff_on: date | None
    payoff_in: str | None  # "7 months"
    interest_left: str | None
    why_not: str | None  # why there is no schedule
    rows: tuple[RowView, ...]
    paid_total: str | None
    interest_total: str | None
    principal_total: str | None


@dataclass(frozen=True)
class HoldingView:
    name: str
    kind: str
    amount: str | None
    since: date | None


@dataclass(frozen=True)
class StandingView:
    owns: tuple[HoldingView, ...]
    owes: tuple[HoldingView, ...]
    owned: str | None
    owed: str | None
    net: str | None
    negative: bool


@dataclass(frozen=True)
class MilestoneView:
    kind: str  # emergency_fund, debt_paid, goal_reached
    on: date
    within: str  # "5 months"
    name: str
    on_track: bool | None


@dataclass(frozen=True)
class MomentView:
    kind: str  # thirteenth_month, ahead
    on: date  # the day, or the month's first day for a month
    month_only: bool
    title: str
    value: str


@dataclass(frozen=True)
class DecisionLine:
    id: uuid.UUID
    question: str
    chosen: str
    on: date
    session_title: str
    revisit: int


@dataclass(frozen=True)
class MoneyScreen:
    as_of: date
    tiles: tuple[Tile, ...]
    split: SplitView | None
    plan: PlanVersion
    before: PlanVersion | None
    debts: tuple[DebtView, ...]
    standing: StandingView
    milestones: tuple[MilestoneView, ...]
    moments: tuple[MomentView, ...]
    decisions: tuple[DecisionLine, ...]  # in force, newest first


def percent(part: int, total: int) -> str:
    """A share as a whole percentage, rounded half up: "60%"."""
    if total <= 0:
        return "—"
    share = (Decimal(part) * 100 / Decimal(total)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"{share}%"


def _fill(part: int | None, whole: int) -> float:
    if part is None or whole <= 0:
        return 0.0
    return round(min(max(part / whole, 0.0), 1.0), 4)


def _figure(run: Run, key: str) -> str:
    return figure_value(run.get(key))


def split_view(split: Split | None) -> SplitView | None:
    if split is None:
        return None
    parts = [
        ("needs", "Needs", split.needs),
        ("wants", "Wants", split.wants),
        ("debt", "Debt", split.debt),
        ("savings", "Savings", split.savings),
        ("unplanned", "Not planned yet", split.unplanned),
    ]
    return SplitView(
        total=money(split.total),
        parts=tuple(
            SplitPart(key, label, amount, money(amount), percent(amount, split.total))
            for key, label, amount in parts
            if amount > 0
        ),
        over=money(split.over) if split.over else None,
    )


def plan_version(
    label: str,
    on: date,
    lines: Sequence[PlanLine],
    changes: Mapping[tuple[uuid.UUID, str], int | None],
) -> PlanVersion:
    pay = sum(line.amount or 0 for line in lines if line.kind == "in")
    views = []
    for line in lines:
        key = (line.entity_id, line.attribute)
        change = None
        if key in changes:
            was = changes[key]
            change = "new" if was is None else f"was {money(was)}"
        views.append(
            LineView(
                kind=line.kind,
                name=line.name,
                amount=None if line.amount is None else money(line.amount),
                left=None if line.left is None else money(line.left),
                fill=_fill(line.left, pay),
                change=change,
            )
        )
    end = lines[-1].left if lines else None
    return PlanVersion(label, on, tuple(views), None if end is None else money(end))


def _rate(snapshot: Snapshot, entity_id: uuid.UUID) -> str | None:
    for attribute in ("debt.monthly_rate", "debt.annual_rate"):
        fact = snapshot.get(entity_id, attribute)
        if fact is not None:
            return fact_value(fact)
    return None


def debt_view(
    holding: Holding,
    schedule: DebtSchedule | None,
    run: Run,
    snapshot: Snapshot,
    paid_in: Mapping[int, Sequence[str]] | None = None,
) -> DebtView:
    minimum_fact = snapshot.get(holding.entity_id, "debt.minimum_payment")
    extra_fact = snapshot.get(holding.entity_id, "plan.allocation")
    minimum = minimum_fact.value_money if minimum_fact is not None else None
    extra = extra_fact.value_money if extra_fact is not None else 0
    try:
        months_figure = run.get("debt.payoff_months", holding.entity_id)
        payoff_on = run.value("debt.payoff_date", holding.entity_id)
        interest = run.value("debt.total_interest", holding.entity_id)
        order = run.value("debt.strategy_order", holding.entity_id)
    except KeyError:  # paid off: no debt figures
        months_figure, payoff_on, interest, order = None, None, None, None
    why_not = None
    if months_figure is not None and months_figure.value is None:
        why_not = flag_words(months_figure.flag)
    rows: tuple[RowView, ...] = ()
    totals: tuple[str | None, str | None, str | None] = (None, None, None)
    if schedule is not None:
        rows = tuple(
            RowView(
                month=r.month,
                on=r.on,
                owed=money(r.owed),
                interest=money(r.interest),
                payment=money(r.payment),
                principal=money(r.principal),
                left=money(r.left),
                fill=_fill(r.left, schedule.balance),
                rolled_in=money(r.rolled_in) if r.rolled_in else None,
                rolled_from=" and ".join((paid_in or {}).get(r.month - 1, ())) or None
                if r.rolled_in
                else None,
            )
            for r in schedule.rows
        )
        if schedule.months is not None:
            totals = (
                money(schedule.paid),
                money(schedule.interest),
                money(schedule.paid - schedule.interest),
            )
    return DebtView(
        id=holding.entity_id,
        name=holding.name,
        order=order if isinstance(order, int) else None,
        balance=money(holding.amount) if holding.amount is not None else "unknown",
        since=holding.since,
        rate=_rate(snapshot, holding.entity_id),
        minimum=None if minimum is None else money(minimum),
        extra=money(extra) if extra else None,
        paying=None if minimum is None else money(minimum + (extra or 0)),
        payoff_on=payoff_on if isinstance(payoff_on, date) else None,
        payoff_in=months(months_figure.value)
        if months_figure is not None and isinstance(months_figure.value, int)
        else None,
        interest_left=money(interest) if isinstance(interest, int) else None,
        why_not=why_not,
        rows=rows,
        paid_total=totals[0],
        interest_total=totals[1],
        principal_total=totals[2],
    )


def _holding(h: Holding) -> HoldingView:
    return HoldingView(h.name, h.kind, None if h.amount is None else money(h.amount), h.since)


def moments(
    snapshot: Snapshot, facts: Sequence[FactRow], entities: Mapping[uuid.UUID, EntityRow]
) -> tuple[MomentView, ...]:
    """13th-month pay this December, and each fact that takes effect after the household's date."""
    on = snapshot.on
    found: list[MomentView] = []
    for fact in snapshot.facts:
        if fact.attribute == "income.thirteenth_month" and (fact.value_money or 0) > 0:
            entity = entities.get(fact.entity_id) if fact.entity_id else None
            title = fact_title(fact, entity)
            found.append(
                MomentView("thirteenth_month", date(on.year, 12, 1), True, title, fact_value(fact))
            )
    for fact in facts:
        if fact.valid_from > on and fact.status != "retracted":
            entity = entities.get(fact.entity_id) if fact.entity_id else None
            found.append(
                MomentView(
                    "ahead", fact.valid_from, False, fact_title(fact, entity), fact_value(fact)
                )
            )
    return tuple(sorted(found, key=lambda m: (m.on, m.title)))


def money_screen(
    facts: Sequence[FactRow], entities: Sequence[EntityRow], household_id: uuid.UUID, on: date
) -> MoneyScreen:
    """Everything on the money screen, worked out from the household's facts on its date. Pure:
    `read_money` gives it the rows, so a test can give it the worked example's."""
    snapshot = take_snapshot(household_id, facts, on)
    view = money_view(snapshot, entities)
    run = view.run
    by_id = {e.id: e for e in entities}

    before_on = plan_before(facts, snapshot)
    before: PlanVersion | None = None
    changes: dict[tuple[uuid.UUID, str], int | None] = {}
    if before_on is not None:
        earlier = take_snapshot(household_id, facts, before_on)
        before_lines = plan_lines(Inputs(earlier, entities))
        changes = line_changes(view.lines, before_lines)
        changed = before_on + timedelta(days=1)
        before = plan_version(f"Before {day(changed)}", before_on, before_lines, {})
        plan = plan_version(f"From {day(changed)}", on, view.lines, changes)
    else:
        plan = plan_version(f"On {day(on)}", on, view.lines, {})

    net = view.standing.net
    tiles = (
        Tile("Total salary", _figure(run, "cashflow.monthly_income"), False),
        Tile(
            "Free after expenses",
            _figure(run, "cashflow.monthly_surplus"),
            run.get("cashflow.monthly_surplus").flag == "negative",
        ),
        Tile("Emergency cover", _figure(run, "savings.emergency_runway_months"), False),
        Tile("Net worth", "unknown" if net is None else money(net), net is not None and net < 0),
    )
    schedules = {s.entity_id: s for s in view.schedules}
    paid_in: dict[int, list[str]] = {}
    for s in view.schedules:
        if s.months is not None:
            paid_in.setdefault(s.months, []).append(s.name)
    st = view.standing
    return MoneyScreen(
        as_of=on,
        tiles=tiles,
        split=split_view(view.split),
        plan=plan,
        before=before,
        debts=tuple(
            debt_view(h, schedules.get(h.entity_id), run, snapshot, paid_in) for h in st.owes
        ),
        standing=StandingView(
            owns=tuple(_holding(h) for h in st.owns),
            owes=tuple(_holding(h) for h in st.owes),
            owned=None if st.owned is None else money(st.owned),
            owed=None if st.owed is None else money(st.owed),
            net=None if net is None else money(net),
            negative=net is not None and net < 0,
        ),
        milestones=tuple(
            MilestoneView(m.kind, m.on, months(m.months), m.name, m.on_track)
            for m in view.milestones
        ),
        moments=moments(snapshot, facts, by_id),
        decisions=(),
    )
