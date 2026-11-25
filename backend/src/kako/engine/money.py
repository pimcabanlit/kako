"""The money screen's numbers (docs/data-model.md, "Calculations", "The money screen").

Worked out from one snapshot and its run, like every figure, and pure like the rest of the engine:

- **The month's plan, line by line** (M-1): take-home pay at the top, then each expense, each debt's
  minimum, each extra allocation to a debt, each allocation to an account and a goal, with what is
  left after each line. What is left at the end is `plan.unallocated`.
- **Where each peso goes** (M-2): the same lines in four parts, needs (essential spending), wants
  (the rest of the spending), debt (minimums and extra payments) and savings (allocations to
  accounts and goals), plus what isn't planned yet. The parts add up to the take-home pay.
- **Each debt's schedule** (M-3): F-DEBT-2's months, one row each: what was owed, the interest,
  the payment, the principal and what is left, and the month a paid-off debt's payment rolls in.
- **Where the household stands** (M-4): what it owns (account balances and what goals have set
  aside) and what it owes (debt balances), and the difference, its net worth.
- **The milestones ahead** (M-5): the emergency fund at its target, each debt paid off, each goal
  reached, from the figures.
- **The plan before its last change** (M-6): the day the month's plan last changed (a new value of a
  fact a line reads), so the screen can show the plan the day before beside it, line by line.

A value the snapshot doesn't have stays unknown (None), and so does everything built from it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from kako.engine.arith import ratio
from kako.engine.dates import add_months
from kako.engine.debts import Debt, Payoff, Strategy, simulate, strategy_order
from kako.engine.engine import compute
from kako.engine.figures import Run
from kako.engine.inputs import Inputs
from kako.facts.model import EntityRow, FactRow
from kako.facts.snapshot import Snapshot

LineKind = Literal["in", "need", "want", "debt", "savings"]
MilestoneKind = Literal["emergency_fund", "debt_paid", "goal_reached"]

# How many months of a schedule are kept when a debt never pays off: enough to show why.
NEVER_ROWS = 12


@dataclass(frozen=True)
class PlanLine:
    kind: LineKind
    name: str  # the thing's name, or the line's words: "Credit card minimum"
    entity_id: uuid.UUID
    attribute: str  # the fact the amount is: income.monthly_net, plan.allocation …
    amount: int | None  # centavos a month; None when the fact is missing
    left: int | None  # what is left after this line; None once any amount above is unknown


@dataclass(frozen=True)
class Split:
    needs: int
    wants: int
    debt: int
    savings: int
    unplanned: int  # what isn't planned yet: 0 when over-planned (see `over`)
    over: int  # how far the plan goes over the pay, 0 when it doesn't
    total: int  # take-home pay

    def share(self, part: int) -> Decimal | None:
        return None if self.total <= 0 else ratio(part, self.total)


@dataclass(frozen=True)
class ScheduleRow:
    month: int  # 1 is the first month after the as-of date
    on: date  # the as-of date + `month` months
    owed: int  # at the start of the month
    interest: int
    payment: int
    principal: int  # payment - interest; negative when the interest is more than the payment
    left: int  # owed + interest - payment
    rolled_in: int  # added to the payment this month from a debt paid off, 0 otherwise


@dataclass(frozen=True)
class DebtSchedule:
    entity_id: uuid.UUID
    name: str
    order: int  # its place in the strategy order (1 first)
    balance: int
    minimum: int
    extra: int  # plan.allocation
    months: int | None  # None: it never pays off
    rows: tuple[ScheduleRow, ...]  # every month to the payoff, or the first NEVER_ROWS

    @property
    def paid(self) -> int:
        return sum(r.payment for r in self.rows)

    @property
    def interest(self) -> int:
        return sum(r.interest for r in self.rows)


@dataclass(frozen=True)
class Holding:
    entity_id: uuid.UUID
    kind: str  # account, goal or debt
    name: str
    amount: int | None
    since: date | None  # the day its fact holds from: a statement's date


@dataclass(frozen=True)
class Standing:
    owns: tuple[Holding, ...]  # accounts, then goals
    owes: tuple[Holding, ...]  # debts in strategy order, or by name
    owned: int | None
    owed: int | None

    @property
    def net(self) -> int | None:
        return None if self.owned is None or self.owed is None else self.owned - self.owed


@dataclass(frozen=True)
class Milestone:
    kind: MilestoneKind
    on: date
    months: int
    entity_id: uuid.UUID | None
    name: str
    on_track: bool | None  # a goal against its target date; None for the others


@dataclass(frozen=True)
class MoneyView:
    on: date
    run: Run
    lines: tuple[PlanLine, ...]
    split: Split | None  # None when a line's amount is unknown
    schedules: tuple[DebtSchedule, ...]  # empty when the order or a debt's facts are missing
    standing: Standing
    milestones: tuple[Milestone, ...]  # soonest first


def _money(inputs: Inputs, entity_id: uuid.UUID | None, attribute: str) -> int | None:
    found = inputs.get(entity_id, attribute)
    if found is None:
        return None
    value = found.value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(f"{attribute} isn't money")


def _text(inputs: Inputs, entity_id: uuid.UUID | None, attribute: str) -> str | None:
    found = inputs.get(entity_id, attribute)
    return found.value if found is not None and isinstance(found.value, str) else None


def _rate(inputs: Inputs, entity_id: uuid.UUID, attribute: str) -> Decimal | None:
    found = inputs.get(entity_id, attribute)
    return found.value if found is not None and isinstance(found.value, Decimal) else None


def _allocation(inputs: Inputs, entity_id: uuid.UUID) -> int:
    return _money(inputs, entity_id, "plan.allocation") or 0


def _open_debts(inputs: Inputs) -> list[EntityRow] | None:
    """F-DEBT-1's open debts: those owing something. None when a balance is missing."""
    found = []
    for e in inputs.open_entities("debt"):
        balance = _money(inputs, e.id, "debt.balance")
        if balance is None:
            return None
        if balance > 0:
            found.append(e)
    return found


def _ordered_debts(inputs: Inputs, entities: list[EntityRow]) -> list[Debt] | None:
    """The open debts in F-DEBT-3's order, as F-DEBT-2 pays them; None when it can't be known."""
    debts = []
    for e in entities:
        balance = _money(inputs, e.id, "debt.balance")
        minimum = _money(inputs, e.id, "debt.minimum_payment")
        monthly = _rate(inputs, e.id, "debt.monthly_rate")
        annual = _rate(inputs, e.id, "debt.annual_rate")
        if balance is None or minimum is None or (monthly is None) == (annual is None):
            return None
        rate = Debt.rate_from(monthly, annual)
        debts.append(Debt(e.id, e.name, balance, rate, minimum, _allocation(inputs, e.id)))
    if len(debts) <= 1:
        return debts
    chosen = _text(inputs, None, "preference.debt_strategy")
    if chosen not in ("avalanche", "snowball"):
        return None
    strategy: Strategy = "avalanche" if chosen == "avalanche" else "snowball"
    return strategy_order(debts, strategy)


def _rows(on: date, debt: Debt, payoff: Payoff) -> tuple[ScheduleRow, ...]:
    rows = []
    owed = debt.balance
    count = len(payoff.payments) if payoff.months is not None else NEVER_ROWS
    for i, (paid, charged, due) in enumerate(
        zip(payoff.payments[:count], payoff.interest[:count], payoff.due[:count], strict=True)
    ):
        left = owed + charged - paid
        rolled = due - payoff.due[i - 1] if i > 0 and due > payoff.due[i - 1] else 0
        rows.append(
            ScheduleRow(
                month=i + 1,
                on=add_months(on, i + 1),
                owed=owed,
                interest=charged,
                payment=paid,
                principal=paid - charged,
                left=left,
                rolled_in=rolled,
            )
        )
        owed = left
    return tuple(rows)


def debt_schedules(inputs: Inputs) -> tuple[DebtSchedule, ...]:
    """M-3: each open debt's months, from the same simulation as F-DEBT-2, in strategy order."""
    entities = _open_debts(inputs)
    if not entities:
        return ()
    ordered = _ordered_debts(inputs, entities)
    if ordered is None:
        return ()
    payoffs = simulate(ordered)
    return tuple(
        DebtSchedule(
            entity_id=d.entity_id,
            name=d.name,
            order=place,
            balance=d.balance,
            minimum=d.minimum,
            extra=d.extra,
            months=payoffs[d.entity_id].months,
            rows=_rows(inputs.on, d, payoffs[d.entity_id]),
        )
        for place, d in enumerate(ordered, start=1)
    )


def plan_lines(inputs: Inputs) -> tuple[PlanLine, ...]:
    """M-1: the month's plan from take-home pay down to what is left unplanned."""
    raw: list[tuple[LineKind, str, uuid.UUID, str, int | None]] = []
    for e in inputs.open_entities("income"):
        raw.append(
            ("in", e.name, e.id, "income.monthly_net", _money(inputs, e.id, "income.monthly_net"))
        )
    spending = []
    for e in inputs.open_entities("expense"):
        amount = _money(inputs, e.id, "expense.monthly_amount")
        kind: LineKind = "need" if _text(inputs, e.id, "expense.essential") == "yes" else "want"
        spending.append((kind, e.name, e.id, "expense.monthly_amount", amount))
    # Needs before wants; within each, the biggest first (then by name, as the entities are sorted).
    spending.sort(key=lambda line: (line[0] != "need", -(line[4] or 0)))
    raw += spending
    debts = _open_debts(inputs) or []
    ordered = _ordered_debts(inputs, debts) if debts else []
    by_order = [d.entity_id for d in ordered] if ordered else [d.id for d in debts]
    names = {d.id: d.name for d in debts}
    for debt_id in by_order:
        amount = _money(inputs, debt_id, "debt.minimum_payment")
        raw.append(("debt", f"{names[debt_id]} minimum", debt_id, "debt.minimum_payment", amount))
    for debt_id in by_order:
        if extra := _allocation(inputs, debt_id):
            raw.append(("debt", f"{names[debt_id]}, extra", debt_id, "plan.allocation", extra))
    for kind_of in ("account", "goal"):
        for e in inputs.open_entities(kind_of):
            if amount := _allocation(inputs, e.id):
                raw.append(("savings", e.name, e.id, "plan.allocation", amount))

    lines = []
    left: int | None = 0
    for kind, name, entity_id, attribute, amount in raw:
        if left is not None and amount is not None:
            left = left + amount if kind == "in" else left - amount
        else:
            left = None
        lines.append(PlanLine(kind, name, entity_id, attribute, amount, left))
    return tuple(lines)


def split_of(lines: Iterable[PlanLine]) -> Split | None:
    """M-2: the plan's lines in four parts and what isn't planned yet."""
    parts = {"in": 0, "need": 0, "want": 0, "debt": 0, "savings": 0}
    for line in lines:
        if line.amount is None:
            return None
        parts[line.kind] += line.amount
    left = parts["in"] - parts["need"] - parts["want"] - parts["debt"] - parts["savings"]
    return Split(
        needs=parts["need"],
        wants=parts["want"],
        debt=parts["debt"],
        savings=parts["savings"],
        unplanned=max(left, 0),
        over=max(-left, 0),
        total=parts["in"],
    )


def _since(snapshot: Snapshot, entity_id: uuid.UUID, attribute: str) -> date | None:
    fact = snapshot.get(entity_id, attribute)
    return fact.valid_from if fact is not None else None


def standing(snapshot: Snapshot, inputs: Inputs, order: list[uuid.UUID]) -> Standing:
    """M-4: what the household owns and owes on the as-of date."""
    owns = [
        Holding(e.id, "account", e.name, _money(inputs, e.id, "account.balance"),
                _since(snapshot, e.id, "account.balance"))
        for e in inputs.open_entities("account")
    ] + [
        Holding(e.id, "goal", e.name, _money(inputs, e.id, "goal.saved_amount"),
                _since(snapshot, e.id, "goal.saved_amount"))
        for e in inputs.open_entities("goal")
    ]  # fmt: skip
    debts = sorted(
        inputs.open_entities("debt"),
        key=lambda e: order.index(e.id) if e.id in order else len(order),
    )
    owes = [
        Holding(e.id, "debt", e.name, _money(inputs, e.id, "debt.balance"),
                _since(snapshot, e.id, "debt.balance"))
        for e in debts
    ]  # fmt: skip

    def total(items: list[Holding]) -> int | None:
        amounts = [h.amount for h in items]
        return None if None in amounts else sum(a for a in amounts if a is not None)

    return Standing(tuple(owns), tuple(owes), total(owns), total(owes))


def milestones(run: Run, entities: Iterable[EntityRow]) -> tuple[Milestone, ...]:
    """M-5: what the figures say is ahead, soonest first; reached ones (0 months) are left out."""
    names = {e.id: e.name for e in entities}
    found = []
    months = run.value("savings.months_to_target")
    if isinstance(months, int) and months > 0:
        found.append(
            Milestone("emergency_fund", add_months(run.as_of, months), months, None,
                      "Emergency fund", None)
        )  # fmt: skip
    for figure in run.figures:
        if figure.entity_id is None or not isinstance(figure.value, int) or figure.value <= 0:
            continue
        if figure.key == "debt.payoff_months":
            found.append(
                Milestone("debt_paid", add_months(run.as_of, figure.value), figure.value,
                          figure.entity_id, names.get(figure.entity_id, ""), None)
            )  # fmt: skip
        elif figure.key == "goal.months_to_target":
            on_track = run.value("goal.on_track", figure.entity_id)
            found.append(
                Milestone("goal_reached", add_months(run.as_of, figure.value), figure.value,
                          figure.entity_id, names.get(figure.entity_id, ""),
                          None if on_track is None else on_track == 1)
            )  # fmt: skip
    return tuple(sorted(found, key=lambda m: (m.on, m.name)))


# The facts M-1's lines read: a new value of any of them changes the month's plan.
PLAN_ATTRIBUTES = frozenset(
    {
        "income.monthly_net",
        "expense.monthly_amount",
        "expense.essential",
        "debt.minimum_payment",
        "plan.allocation",
    }
)


def plan_changed_on(snapshot: Snapshot) -> date | None:
    """The latest day on or before the as-of date that a fact the plan reads took effect."""
    days = [f.valid_from for f in snapshot.facts if f.attribute in PLAN_ATTRIBUTES]
    return max(days) if days else None


def plan_before(facts: Iterable[FactRow], snapshot: Snapshot) -> date | None:
    """M-6: the day before the plan's last change, when the plan had lines before it (its first
    values aren't a change). Reads every fact, since the snapshot holds only today's."""
    changed = plan_changed_on(snapshot)
    if changed is None:
        return None
    earlier = [
        f for f in facts
        if f.attribute in PLAN_ATTRIBUTES and f.valid_from < changed and f.status != "retracted"
    ]  # fmt: skip
    return changed - timedelta(days=1) if earlier else None


def line_changes(
    now: Iterable[PlanLine], before: Iterable[PlanLine]
) -> dict[tuple[uuid.UUID, str], int | None]:
    """Each line that differs from the plan before: the amount it was, or None for a new line."""
    was = {(line.entity_id, line.attribute): line.amount for line in before}
    changed: dict[tuple[uuid.UUID, str], int | None] = {}
    for line in now:
        key = (line.entity_id, line.attribute)
        if key not in was:
            changed[key] = None
        elif was[key] != line.amount and was[key] is not None:
            changed[key] = was[key]
    return changed


def money_view(snapshot: Snapshot, entities: Iterable[EntityRow]) -> MoneyView:
    """Everything the money screen shows for one snapshot."""
    entities = list(entities)
    run = compute(snapshot, entities)
    inputs = Inputs(snapshot, entities)
    lines = plan_lines(inputs)
    schedules = debt_schedules(inputs)
    return MoneyView(
        on=snapshot.on,
        run=run,
        lines=lines,
        split=split_of(lines),
        schedules=schedules,
        standing=standing(snapshot, inputs, [s.entity_id for s in schedules]),
        milestones=milestones(run, entities),
    )
