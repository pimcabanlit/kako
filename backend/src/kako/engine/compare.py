"""Before and after an option (docs/data-model.md, "Before and after an option", C-1 to C-3).

An option is a what-if: the turn's snapshot with its allocations as overrides. Set beside the
turn's own run (today's plan), it shows what the option changes, worked out here and never by an
agent:

- **What each run reaches** (C-1): each open debt's payoff (months and date) and its interest, the
  interest on every debt together, the emergency fund at its target, each goal reached, and what
  is left unplanned a month, all read from the run's figures.
- **What changes** (C-2): each of those against today's plan: how many months sooner or later, how
  many pesos less or more interest, reached where it wasn't, or never reached where it was, and
  whether that is better, worse or the same for the household.
- **Month by month** (C-3): each debt's schedule with the option (M-3) beside its balance in
  today's plan that month, and the emergency fund growing by its allocation each month to its
  target (F-SAV-3's own quantities).

Pure like the rest of the engine: runs, schedules and inputs in, values out.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from kako.engine.dates import add_months
from kako.engine.figures import Run
from kako.engine.inputs import Inputs
from kako.engine.money import DebtSchedule, ScheduleRow, debt_schedules
from kako.facts.model import EntityRow

OutcomeKind = Literal[
    "debt_paid", "debt_interest", "interest_total", "emergency_fund", "goal_reached", "unplanned"
]
Direction = Literal["better", "worse", "same", "none"]  # none: nothing to compare
ChangeKind = Literal["sooner", "later", "less", "more", "reached", "never", "same", "none"]

# How many months of the emergency fund's growth are kept: ten years shows any fund that matters.
CLIMB_ROWS = 120

# A payoff or target with no months for one of these reasons is never reached at this plan; any
# other reason (a missing fact, no strategy) means it isn't known, so there is nothing to compare.
NEVER: frozenset[str] = frozenset({"never_pays_off", "no_allocation"})


@dataclass(frozen=True)
class Outcome:
    """One thing a run reaches (C-1): a row of the comparison in one run."""

    kind: OutcomeKind
    entity_id: uuid.UUID | None
    name: str  # the debt's, account's or goal's name; "" for the totals
    months: int | None  # for a payoff or a target: months until then; None: never (see `flag`)
    on: date | None  # the date of that month
    amount: int | None  # centavos: interest, or what is left unplanned
    flag: str | None  # why a value is missing, as the figure says

    @property
    def never(self) -> bool:
        return self.months is None and self.flag in NEVER


@dataclass(frozen=True)
class Change:
    """C-2: an outcome with the option against today's plan."""

    kind: ChangeKind
    direction: Direction
    months: int | None  # how many months sooner or later
    amount: int | None  # how many centavos less or more


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def outcomes(run: Run, entities: Iterable[EntityRow]) -> tuple[Outcome, ...]:
    """C-1: what a run reaches, in a fixed order: each debt in strategy order (paid off, then its
    interest), the interest on every debt, the emergency fund, each goal by name, what is left
    unplanned."""
    names = {e.id: e.name for e in entities}
    debts = sorted(
        (f for f in run.figures if f.key == "debt.payoff_months" and f.entity_id is not None),
        key=lambda f: (
            _int(run.value("debt.strategy_order", f.entity_id)) or 0,
            names.get(f.entity_id, "") if f.entity_id else "",
        ),
    )
    found: list[Outcome] = []
    interests: list[int | None] = []
    for figure in debts:
        entity_id = figure.entity_id
        name = names.get(entity_id, "") if entity_id else ""
        months = _int(figure.value)
        payoff_on = run.value("debt.payoff_date", entity_id)
        found.append(
            Outcome("debt_paid", entity_id, name, months,
                    payoff_on if isinstance(payoff_on, date) else None, None, figure.flag)
        )  # fmt: skip
        total = run.get("debt.total_interest", entity_id)
        interests.append(_int(total.value))
        found.append(
            Outcome("debt_interest", entity_id, name, None, None, _int(total.value), total.flag)
        )
    if len(debts) > 1:
        known = None if any(i is None for i in interests) else sum(i or 0 for i in interests)
        found.append(Outcome("interest_total", None, "", None, None, known, None))
    fund = run.get("savings.months_to_target")
    fund_months = _int(fund.value)
    found.append(
        Outcome("emergency_fund", None, "Emergency fund", fund_months,
                None if fund_months is None else add_months(run.as_of, fund_months), None,
                fund.flag)
    )  # fmt: skip
    goals = sorted(
        (f for f in run.figures if f.key == "goal.months_to_target" and f.entity_id is not None),
        key=lambda f: names.get(f.entity_id, "") if f.entity_id else "",
    )
    for figure in goals:
        projected = run.value("goal.projected_date", figure.entity_id)
        found.append(
            Outcome("goal_reached", figure.entity_id,
                    names.get(figure.entity_id, "") if figure.entity_id else "",
                    _int(figure.value), projected if isinstance(projected, date) else None,
                    None, figure.flag)
        )  # fmt: skip
    unplanned = run.get("plan.unallocated")
    found.append(Outcome("unplanned", None, "", None, None, _int(unplanned.value), unplanned.flag))
    return tuple(found)


def change(before: Outcome, after: Outcome) -> Change:
    """C-2: what the option changes in one outcome, and whether that is better for the household.

    Time to a payoff or a target: fewer months is better, reaching it where today's plan never
    does is better, never reaching it where today's plan does is worse. Interest: less is better.
    What is left unplanned has no better or worse: it is the household's to plan."""
    if before.kind != after.kind or before.entity_id != after.entity_id:
        raise ValueError("compare an outcome with the same outcome in the other run")
    if after.kind in ("debt_paid", "emergency_fund", "goal_reached"):
        known = (before.months is not None or before.never, after.months is not None or after.never)
        if not all(known):
            return Change("none", "none", None, None)
        if before.months is None and after.months is None:
            return Change("same", "same", None, None)
        if before.months is None:
            return Change("reached", "better", after.months, None)
        if after.months is None:
            return Change("never", "worse", None, None)
        gap = before.months - after.months
        if gap > 0:
            return Change("sooner", "better", gap, None)
        if gap < 0:
            return Change("later", "worse", -gap, None)
        return Change("same", "same", 0, None)
    if before.amount is None or after.amount is None:
        return Change("none", "none", None, None)
    gap = before.amount - after.amount
    if after.kind == "unplanned":
        return Change("none", "none", None, -gap)
    if gap > 0:
        return Change("less", "better", None, gap)
    if gap < 0:
        return Change("more", "worse", None, -gap)
    return Change("same", "same", None, 0)


# --- Month by month (C-3) ------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthRow:
    row: ScheduleRow  # the option's month (M-3)
    before_left: int | None  # the balance in today's plan that month; None past what it shows


@dataclass(frozen=True)
class DebtMonths:
    entity_id: uuid.UUID
    name: str
    balance: int  # owed on the as-of date
    months: int | None  # with the option; None: never paid off
    before_months: int | None
    rows: tuple[MonthRow, ...]
    paid: int  # with the option, over the months shown
    interest: int
    before_interest: int | None  # today's plan's interest to its payoff; None: never paid off
    before_left_then: int | None  # today's plan's balance in the option's last month
    paid_in: dict[int, tuple[str, ...]]  # the month each debt is paid off, with the option


@dataclass(frozen=True)
class FundMonth:
    month: int
    on: date
    added: int
    balance: int  # what the liquid accounts hold after this month's allocation
    to_go: int  # what is still short of the target, 0 once reached


@dataclass(frozen=True)
class FundClimb:
    entity_id: uuid.UUID
    name: str
    target: int
    start: int  # the liquid balance on the as-of date (F-SAV-1's)
    monthly: int  # the emergency fund's allocation with the option
    months: int  # F-SAV-3's months to the target
    rows: tuple[FundMonth, ...]  # month by month, at most CLIMB_ROWS


def _before_left(before: DebtSchedule | None, month: int) -> int | None:
    if before is None:
        return None
    if before.months is not None and month > before.months:
        return 0  # paid off already
    if month > len(before.rows):
        return None  # never paid off: only its first months are shown
    return before.rows[month - 1].left


def debt_months(after: Inputs, before: Inputs) -> tuple[DebtMonths, ...]:
    """C-3: each open debt with the option, month by month, beside today's plan."""
    schedules = debt_schedules(after)
    earlier = {s.entity_id: s for s in debt_schedules(before)}
    paid_in: dict[int, list[str]] = {}
    for s in schedules:
        if s.months is not None:
            paid_in.setdefault(s.months, []).append(s.name)
    found = []
    for s in schedules:
        was = earlier.get(s.entity_id)
        last = s.rows[-1].month if s.rows else 0
        found.append(
            DebtMonths(
                entity_id=s.entity_id,
                name=s.name,
                balance=s.balance,
                months=s.months,
                before_months=was.months if was is not None else None,
                rows=tuple(MonthRow(r, _before_left(was, r.month)) for r in s.rows),
                paid=s.paid,
                interest=s.interest,
                before_interest=was.interest
                if was is not None and was.months is not None
                else None,
                before_left_then=_before_left(was, last) if s.months is not None else None,
                paid_in={m: tuple(n) for m, n in paid_in.items()},
            )
        )
    return tuple(found)


def _liquid(inputs: Inputs) -> int | None:
    """F-SAV-1's liquid balance: the balances of the open accounts marked liquid."""
    total = 0
    for a in inputs.open_entities("account"):
        liquid = inputs.get(a.id, "account.liquid")
        if liquid is None:
            return None
        if liquid.value == "yes":
            balance = inputs.get(a.id, "account.balance")
            if balance is None or not isinstance(balance.value, int):
                return None
            total += balance.value
    return total


def fund_climb(inputs: Inputs, run: Run) -> FundClimb | None:
    """C-3: the emergency fund reaching its target with this run's allocation, month by month:
    the liquid balance plus the fund's allocation each month, as F-SAV-3 counts it. None when the
    run doesn't reach the target by saving (already there, no fund, nothing going in)."""
    months = _int(run.value("savings.months_to_target"))
    target = _int(run.value("savings.emergency_target"))
    start = _liquid(inputs)
    if not months or target is None or start is None:
        return None
    funds = [
        a
        for a in inputs.open_entities("account")
        if (p := inputs.get(a.id, "account.purpose")) is not None and p.value == "emergency"
    ]
    if len(funds) != 1:
        return None
    fund = funds[0]
    found = inputs.get(fund.id, "plan.allocation")
    monthly = found.value if found is not None and isinstance(found.value, int) else 0
    if monthly <= 0:
        return None
    rows = tuple(
        FundMonth(
            month=k,
            on=add_months(inputs.on, k),
            added=monthly,
            balance=start + monthly * k,
            to_go=max(0, target - start - monthly * k),
        )
        for k in range(1, min(months, CLIMB_ROWS) + 1)
    )
    return FundClimb(fund.id, fund.name, target, start, monthly, months, rows)


def outcome_pairs(
    before: Sequence[Outcome], after: Sequence[Outcome]
) -> tuple[tuple[Outcome, Outcome, Change], ...]:
    """Each outcome of today's plan with the same one in the option's run, and its change."""
    found = {(o.kind, o.entity_id): o for o in after}
    pairs = []
    for b in before:
        a = found.get((b.kind, b.entity_id))
        if a is not None:
            pairs.append((b, a, change(b, a)))
    return tuple(pairs)
