"""Before and after a plan's options, in words: what the session and plan screens show under each
answer with options.

Pure. Today's plan is the turn's snapshot as it stood; each option is the same snapshot with the
option's allocations as overrides, exactly the what-if the agents ran. `engine.compare` works out
what each reaches, what each option changes and the months one by one (C-1 to C-3); this writes
them out with `agents.present`, so every number on screen is the engine's. No agent sees any of it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from kako.agents.present import day, money, months
from kako.engine.compare import (
    CLIMB_ROWS,
    Change,
    DebtMonths,
    FundClimb,
    Outcome,
    debt_months,
    fund_climb,
    outcome_pairs,
    outcomes,
)
from kako.engine.dates import add_months
from kako.engine.engine import compute
from kako.engine.figures import Run
from kako.engine.inputs import Inputs, Override
from kako.facts.model import EntityRow
from kako.facts.snapshot import Snapshot
from kako.planning.why import flag_words

# The outcomes each option card shows in its "Before → after": the dates and the interest in all.
ON_CARD = frozenset({"debt_paid", "interest_total", "emergency_fund", "goal_reached"})
UNKNOWN = "unknown"  # a value no figure can give, with its note saying why


@dataclass(frozen=True)
class Cell:
    value: str  # "Aug 15, 2030", "₱111,635.47", "never"
    note: str | None  # "in 47 months", or why there is no value
    change: str | None  # against today's plan: "38 months sooner", "₱99,175.37 less"
    direction: str  # better, worse, same, none


@dataclass(frozen=True)
class CompareRow:
    key: str  # the outcome and its entity: "debt_paid:<id>"
    kind: str
    label: str  # "Credit card paid off"
    on_card: bool  # one of the few each option card shows
    before: Cell
    options: tuple[Cell, ...]  # in the order of the plan's options


@dataclass(frozen=True)
class OptionHead:
    label: str
    each_month: str  # "₱9,050.00 a month to the Credit card"


@dataclass(frozen=True)
class MonthRowView:
    month: int
    on: date
    payment: str
    interest: str
    principal: str
    left: str
    fill: float  # what is left as a share of today's balance
    before_left: str | None  # today's plan's balance that month
    before_fill: float | None
    rolled_in: str | None
    rolled_from: str | None


@dataclass(frozen=True)
class DebtMonthsView:
    name: str
    paid_off: date | None
    change: str | None  # "38 months sooner than today's plan"
    direction: str
    rows: tuple[MonthRowView, ...]
    paid_total: str
    interest_total: str
    principal_total: str
    closing: str  # "Paid off Jun 15, 2027: ₱97,460.10 paid, ₱12,460.10 of it interest."
    before_closing: str | None  # what today's plan does instead


@dataclass(frozen=True)
class FundMonthView:
    month: int
    on: date
    added: str
    balance: str
    to_go: str | None  # None once the target is reached
    fill: float


@dataclass(frozen=True)
class FundView:
    name: str
    target: str
    reached_on: date
    closing: str
    before_closing: str
    rows: tuple[FundMonthView, ...]


@dataclass(frozen=True)
class OptionMonths:
    label: str
    debts: tuple[DebtMonthsView, ...]
    fund: FundView | None


@dataclass(frozen=True)
class Comparison:
    plan_id: uuid.UUID
    as_of: date
    baseline: str  # today's plan in words
    each_month: str  # what today's plan puts in each month: "the minimums only"
    options: tuple[OptionHead, ...]
    rows: tuple[CompareRow, ...]
    months: tuple[OptionMonths, ...]


def _fill(part: int | None, whole: int) -> float:
    if part is None or whole <= 0:
        return 0.0
    return round(min(max(part / whole, 0.0), 1.0), 4)


def _label(o: Outcome) -> str:
    return {
        "debt_paid": f"{o.name} paid off",
        "debt_interest": f"{o.name} interest",
        "interest_total": "Interest on every debt",
        "emergency_fund": "Emergency fund at its target",
        "goal_reached": f"{o.name} reached",
        "unplanned": "Left unplanned a month",
    }[o.kind]


def _value(o: Outcome) -> tuple[str, str | None]:
    if o.kind in ("debt_paid", "emergency_fund", "goal_reached"):
        if o.months == 0:
            return "already there", None
        if o.months is not None and o.on is not None:
            return day(o.on), f"in {months(o.months)}"
        if o.never:
            return "never", flag_words(o.flag)
        return UNKNOWN, flag_words(o.flag)
    if o.amount is None:
        return UNKNOWN, flag_words(o.flag)
    return money(o.amount), None


def _change_words(o: Outcome, c: Change) -> str | None:
    if c.kind == "sooner":
        return f"{months(c.months or 0)} sooner"
    if c.kind == "later":
        return f"{months(c.months or 0)} later"
    if c.kind == "less":
        return f"{money(c.amount or 0)} less"
    if c.kind == "more":
        return f"{money(c.amount or 0)} more"
    if c.kind == "reached":
        done = "paid off" if o.kind == "debt_paid" else "reached"
        return f"{done} in {months(c.months or 0)}"
    if c.kind == "never":
        return "never paid off" if o.kind == "debt_paid" else "never reached"
    if c.kind == "same":
        return "no change"
    return None


def _cell(o: Outcome, c: Change | None) -> Cell:
    value, note = _value(o)
    if c is None:
        return Cell(value, note, None, "none")
    return Cell(value, note, _change_words(o, c), c.direction)


def _key(o: Outcome) -> str:
    return f"{o.kind}:{o.entity_id}" if o.entity_id else o.kind


def _set_aside(inputs: Inputs, entity_id: uuid.UUID) -> int:
    found = inputs.get(entity_id, "plan.allocation")
    return found.value if found is not None and isinstance(found.value, int) else 0


def _allocations(overrides: Sequence[Override], before: Inputs, names: dict[uuid.UUID, str]) -> str:
    """What the option puts in each month, in the plan's order: debts, accounts, goals. One it
    stops paying into, where today's plan does, is said too."""
    given = {o.entity_id: o.value for o in overrides if o.entity_id is not None}
    parts = []
    for kind in ("debt", "account", "goal"):
        for e in before.open_entities(kind):
            value = given.get(e.id)
            if not isinstance(value, int):
                continue
            if value > 0:
                parts.append(f"{money(value)} a month to the {names[e.id]}")
            elif _set_aside(before, e.id) > 0:
                parts.append(f"nothing to the {names[e.id]}")
    return " and ".join(parts) if parts else "nothing more set aside"


def _today(inputs: Inputs, names: dict[uuid.UUID, str]) -> str:
    """What today's plan puts in each month, beyond the minimums."""
    set_aside = [
        f"{money(_set_aside(inputs, e.id))} a month to the {names[e.id]}"
        for kind in ("debt", "account", "goal")
        for e in inputs.open_entities(kind)
        if _set_aside(inputs, e.id) > 0
    ]
    return " and ".join(set_aside) if set_aside else "the minimums only"


def _baseline(inputs: Inputs, run: Run, names: dict[uuid.UUID, str]) -> str:
    what = _today(inputs, names)
    unplanned = run.value("plan.unallocated")
    text = f"Today's plan on {day(run.as_of)}: {what}"
    if isinstance(unplanned, int) and unplanned > 0:
        text += f", with {money(unplanned)} a month not yet planned"
    return text + "."


def _debt_view(d: DebtMonths, on: date) -> DebtMonthsView:
    rows = tuple(
        MonthRowView(
            month=m.row.month,
            on=m.row.on,
            payment=money(m.row.payment),
            interest=money(m.row.interest),
            principal=money(m.row.principal),
            left=money(m.row.left),
            fill=_fill(m.row.left, d.balance),
            before_left=None if m.before_left is None else money(m.before_left),
            before_fill=None if m.before_left is None else _fill(m.before_left, d.balance),
            rolled_in=money(m.row.rolled_in) if m.row.rolled_in else None,
            rolled_from=" and ".join(d.paid_in.get(m.row.month - 1, ())) or None
            if m.row.rolled_in
            else None,
        )
        for m in d.rows
    )
    paid_off = add_months(on, d.months) if d.months is not None else None
    if paid_off is not None:
        closing = (
            f"Paid off {day(paid_off)}: {money(d.paid)} paid, {money(d.interest)} of it interest."
        )
    else:
        closing = f"Never paid off at this payment: its first {months(len(rows))} are shown."
    change: str | None = None
    direction = "none"
    before_closing: str | None
    if d.before_months is None:
        before_closing = "Today's plan never pays it off."
        if d.months is not None:
            change, direction = "paid off, where today's plan never does", "better"
    else:
        before_on = add_months(on, d.before_months)
        interest = "" if d.before_interest is None else f" with {money(d.before_interest)} interest"
        if d.months is None:
            before_closing = f"Today's plan pays it off {day(before_on)}{interest}."
            change, direction = "never paid off", "worse"
        elif d.before_months > d.months:
            owed = (
                ""
                if d.before_left_then is None
                else f"still owe {money(d.before_left_then)} then, and "
            )
            before_closing = f"Today's plan would {owed}pay it off {day(before_on)}{interest}."
            change = f"{months(d.before_months - d.months)} sooner than today's plan"
            direction = "better"
        elif d.before_months < d.months:
            before_closing = f"Today's plan pays it off sooner: {day(before_on)}{interest}."
            change = f"{months(d.months - d.before_months)} later than today's plan"
            direction = "worse"
        else:
            before_closing = f"Today's plan pays it off the same month{interest}."
            change, direction = "the same month as today's plan", "same"
    return DebtMonthsView(
        name=d.name,
        paid_off=paid_off,
        change=change,
        direction=direction,
        rows=rows,
        paid_total=money(d.paid),
        interest_total=money(d.interest),
        principal_total=money(d.paid - d.interest),
        closing=closing,
        before_closing=before_closing,
    )


def _fund_view(f: FundClimb, on: date, before: Run) -> FundView:
    reached_on = add_months(on, f.months)
    closing = f"At its {money(f.target)} target on {day(reached_on)}, in {months(f.months)}."
    if f.months > CLIMB_ROWS:
        closing += f" The first {months(CLIMB_ROWS)} are shown."
    was = before.get("savings.months_to_target")
    if isinstance(was.value, int) and not isinstance(was.value, bool):
        then = day(add_months(on, was.value))
        before_closing = (
            "Today's plan is there already."
            if was.value == 0
            else f"Today's plan gets there {then}, in {months(was.value)}."
        )
    else:
        before_closing = "Today's plan never gets there: nothing is set aside for it."
    return FundView(
        name=f.name,
        target=money(f.target),
        reached_on=reached_on,
        closing=closing,
        before_closing=before_closing,
        rows=tuple(
            FundMonthView(
                month=r.month,
                on=r.on,
                added=money(r.added),
                balance=money(r.balance),
                to_go=money(r.to_go) if r.to_go > 0 else None,
                fill=_fill(r.balance, f.target),
            )
            for r in f.rows
        ),
    )


def comparison(
    plan_id: uuid.UUID,
    snapshot: Snapshot,
    entities: Iterable[EntityRow],
    options: Sequence[tuple[str, Sequence[Override]]],
) -> Comparison:
    """Today's plan and each option (its label and its allocations as overrides), compared."""
    entities = list(entities)
    names = {e.id: e.name for e in entities}
    before_inputs = Inputs(snapshot, entities)
    before = compute(snapshot, entities)
    reached = outcomes(before, entities)
    afters: list[tuple[Run, Inputs]] = []
    for _, overrides in options:
        afters.append(
            (compute(snapshot, entities, overrides), Inputs(snapshot, entities, overrides))
        )
    pairs = [outcome_pairs(reached, outcomes(run, entities)) for run, _ in afters]
    rows = []
    for i, o in enumerate(reached):
        cells = []
        for found in pairs:
            match = next((p for p in found if p[0] is o), None)
            cells.append(_cell(match[1], match[2]) if match else Cell(UNKNOWN, None, None, "none"))
        before_cell = _cell(o, None)
        # A card leaves out a row no run can tell (a goal missing a fact): the table still shows it.
        known = any(c.value != UNKNOWN for c in (before_cell, *cells))
        card = (o.kind in ON_CARD or _alone(reached, i)) and known
        rows.append(CompareRow(_key(o), o.kind, _label(o), card, before_cell, tuple(cells)))
    return Comparison(
        plan_id=plan_id,
        as_of=snapshot.on,
        baseline=_baseline(before_inputs, before, names),
        each_month=_today(before_inputs, names),
        options=tuple(
            OptionHead(label, _allocations(o, before_inputs, names)) for label, o in options
        ),
        rows=tuple(rows),
        months=tuple(
            OptionMonths(
                label=label,
                debts=tuple(_debt_view(d, snapshot.on) for d in debt_months(inputs, before_inputs)),
                fund=(lambda f: None if f is None else _fund_view(f, snapshot.on, before))(
                    fund_climb(inputs, run)
                ),
            )
            for (label, _), (run, inputs) in zip(options, afters, strict=True)
        ),
    )


def _alone(reached: Sequence[Outcome], i: int) -> bool:
    """A single debt's interest goes on the card, since there is no total of several."""
    return reached[i].kind == "debt_interest" and not any(
        o.kind == "interest_total" for o in reached
    )
