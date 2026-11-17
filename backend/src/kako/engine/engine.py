"""`compute`: every figure in docs/data-model.md, "Calculations", for one snapshot.

The engine never assumes a missing fact. A figure whose formula needs a value that isn't there has
no value and the flag `missing_input`, and so does every figure built from it. The optional facts
are the ones whose absence has a meaning: no `plan.allocation` is 0 a month, and no
`income.thirteenth_month` is no 13th-month pay. Every other fact a formula names is required for
the open entities it reads.

Each figure records the facts (and a what-if's overrides) it read and the figures it was built from.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Final

import kako
from kako.engine.arith import ceil_div, ratio
from kako.engine.dates import HORIZON_MONTHS, add_months, whole_months_until
from kako.engine.debts import Debt, Strategy, simulate, strategy_order
from kako.engine.figures import Figure, FigureRef, FigureValue, Flag, Run, Unit
from kako.engine.inputs import EngineInputError, Inputs, Override, Value
from kako.facts.model import EntityRow, FactValue
from kako.facts.snapshot import Snapshot

__all__ = ["ENGINE_VERSION", "EngineInputError", "compute"]

ENGINE_VERSION: Final = kako.__version__


class _Trace:
    """What one figure read: facts, overrides and other figures."""

    def __init__(self, inputs: Inputs) -> None:
        self.inputs = inputs
        self.facts: set[uuid.UUID] = set()
        self.overrides: set[uuid.UUID] = set()
        self.figures: set[FigureRef] = set()

    def _read(self, entity_id: uuid.UUID | None, attribute: str) -> FactValue | None:
        found: Value | None = self.inputs.get(entity_id, attribute)
        if found is None:
            return None
        if found.fact_id is not None:
            self.facts.add(found.fact_id)
        if found.override_id is not None:
            self.overrides.add(found.override_id)
        return found.value

    def money(self, entity_id: uuid.UUID | None, attribute: str) -> int | None:
        value = self._read(entity_id, attribute)
        if value is None or (isinstance(value, int) and not isinstance(value, bool)):
            return value
        raise EngineInputError(f"{attribute} isn't a whole number")

    count = money  # whole numbers that aren't money (months, a day, a priority)

    def rate(self, entity_id: uuid.UUID | None, attribute: str) -> Decimal | None:
        value = self._read(entity_id, attribute)
        if value is None or isinstance(value, Decimal):
            return value
        raise EngineInputError(f"{attribute} isn't a rate")

    def text(self, entity_id: uuid.UUID | None, attribute: str) -> str | None:
        value = self._read(entity_id, attribute)
        if value is None or isinstance(value, str):
            return value
        raise EngineInputError(f"{attribute} isn't text")

    def day(self, entity_id: uuid.UUID | None, attribute: str) -> date | None:
        value = self._read(entity_id, attribute)
        if value is None or isinstance(value, date):
            return value
        raise EngineInputError(f"{attribute} isn't a date")

    def allocation(self, entity_id: uuid.UUID) -> int:
        """`plan.allocation`, optional: none is ₱0 a month."""
        return self.money(entity_id, "plan.allocation") or 0

    def use(self, figure: Figure) -> FigureValue | None:
        self.figures.add(figure.ref)
        return figure.value


class _Builder:
    def __init__(self, inputs: Inputs) -> None:
        self.inputs = inputs
        self.figures: dict[FigureRef, Figure] = {}

    def trace(self) -> _Trace:
        return _Trace(self.inputs)

    def get(self, key: str, entity_id: uuid.UUID | None = None) -> Figure:
        return self.figures[FigureRef(key, entity_id)]

    def add(
        self,
        key: str,
        unit: Unit,
        formula: str,
        trace: _Trace,
        value: FigureValue | None,
        flag: Flag | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> Figure:
        if value is None and flag is None:
            flag = "missing_input"
        figure = Figure(
            key=key,
            entity_id=entity_id,
            unit=unit,
            value=value,
            flag=flag,
            formula=formula,
            input_fact_ids=tuple(sorted(trace.facts, key=str)),
            input_override_ids=tuple(sorted(trace.overrides, key=str)),
            input_figures=tuple(sorted(trace.figures, key=lambda r: (r.key, str(r.entity_id)))),
        )
        if figure.ref in self.figures:
            raise RuntimeError(f"figure {key} computed twice")
        self.figures[figure.ref] = figure
        return figure

    def open(self, kind: str) -> list[EntityRow]:
        return self.inputs.open_entities(kind)


def _total(values: Iterable[int | None]) -> int | None:
    """A sum that is unknown when any part is."""
    parts = list(values)
    return None if None in parts else sum(p for p in parts if p is not None)


def _int(value: FigureValue | None) -> int | None:
    if value is None or isinstance(value, int):
        return value
    raise TypeError(f"expected centavos, got {value!r}")


# --- Cash flow ---------------------------------------------------------------------------------


def _cashflow(b: _Builder) -> None:
    t = b.trace()
    income = _total(t.money(e.id, "income.monthly_net") for e in b.open("income"))
    b.add("cashflow.monthly_income", "centavos", "F-INC-1", t, income)

    if b.inputs.on.month == 12:  # 13th-month pay is received in December
        t = b.trace()
        pays = [t.money(e.id, "income.thirteenth_month") for e in b.open("income")]
        b.add("cashflow.thirteenth_month", "centavos", "F-INC-1", t, sum(p or 0 for p in pays))

    t = b.trace()
    expenses = _total(t.money(e.id, "expense.monthly_amount") for e in b.open("expense"))
    b.add("cashflow.monthly_expenses", "centavos", "F-EXP-1", t, expenses)

    t = b.trace()
    essential: list[int | None] = []
    for e in b.open("expense"):
        marked = t.text(e.id, "expense.essential")
        if marked is None:
            essential.append(None)
        elif marked == "yes":
            essential.append(t.money(e.id, "expense.monthly_amount"))
    b.add("cashflow.essential_expenses", "centavos", "F-EXP-2", t, _total(essential))

    t = b.trace()
    debts = _open_debts(b, t)
    minimums = (
        None if debts is None else _total(t.money(d.id, "debt.minimum_payment") for d in debts)
    )
    b.add("cashflow.minimum_payments", "centavos", "F-DEBT-1", t, minimums)

    t = b.trace()
    income_v = _int(t.use(b.get("cashflow.monthly_income")))
    expenses_v = _int(t.use(b.get("cashflow.monthly_expenses")))
    minimums_v = _int(t.use(b.get("cashflow.minimum_payments")))
    surplus = None
    if income_v is not None and expenses_v is not None and minimums_v is not None:
        surplus = income_v - expenses_v - minimums_v
    flag: Flag | None = "negative" if surplus is not None and surplus < 0 else None
    b.add("cashflow.monthly_surplus", "centavos", "F-CF-1", t, surplus, flag)

    t = b.trace()
    income_v = _int(t.use(b.get("cashflow.monthly_income")))
    minimums_v = _int(t.use(b.get("cashflow.minimum_payments")))
    _add_ratio(b, "cashflow.debt_payment_share", "F-CF-2", t, minimums_v, income_v, "no_income")

    t = b.trace()
    income_v = _int(t.use(b.get("cashflow.monthly_income")))
    saved = sum(t.allocation(e.id) for kind in ("account", "goal") for e in b.open(kind))
    _add_ratio(b, "cashflow.savings_rate", "F-CF-3", t, saved, income_v, "no_income")


def _add_ratio(
    b: _Builder,
    key: str,
    formula: str,
    t: _Trace,
    numerator: int | None,
    denominator: int | None,
    zero_flag: Flag,
) -> None:
    if numerator is None or denominator is None:
        b.add(key, "ratio", formula, t, None)
    elif denominator == 0:
        b.add(key, "ratio", formula, t, None, zero_flag)
    else:
        b.add(key, "ratio", formula, t, ratio(numerator, denominator))


def _open_debts(b: _Builder, t: _Trace) -> list[EntityRow] | None:
    """The debts that still owe something on the date. None: a balance is missing."""
    found: list[EntityRow] = []
    for e in b.open("debt"):
        balance = t.money(e.id, "debt.balance")
        if balance is None:
            return None
        if balance > 0:
            found.append(e)
    return found


# --- Savings -----------------------------------------------------------------------------------


def _liquid_total(b: _Builder, t: _Trace) -> int | None:
    """The balances of the accounts marked liquid (`account.liquid` = yes)."""
    balances: list[int | None] = []
    for a in b.open("account"):
        liquid = t.text(a.id, "account.liquid")
        if liquid is None:
            balances.append(None)
        elif liquid == "yes":
            balances.append(t.money(a.id, "account.balance"))
    return _total(balances)


def _savings(b: _Builder) -> None:
    t = b.trace()
    liquid = _liquid_total(b, t)
    essential = _int(t.use(b.get("cashflow.essential_expenses")))
    key = "savings.emergency_runway_months"
    _add_ratio(b, key, "F-SAV-1", t, liquid, essential, "no_essential_expenses")

    t = b.trace()
    months = t.count(None, "household.emergency_months_target")
    essential = _int(t.use(b.get("cashflow.essential_expenses")))
    target = None if months is None or essential is None else months * essential
    b.add("savings.emergency_target", "centavos", "F-SAV-2", t, target)

    t = b.trace()
    target = _int(t.use(b.get("savings.emergency_target")))
    liquid = _liquid_total(b, t)
    funds: list[EntityRow] = []
    purpose_missing = False
    for a in b.open("account"):
        purpose = t.text(a.id, "account.purpose")
        purpose_missing = purpose_missing or purpose is None
        if purpose == "emergency":
            funds.append(a)
    if len(funds) > 1:
        raise EngineInputError("two accounts are the emergency fund on the same date (V-16)")
    key = "savings.months_to_target"
    if target is None or liquid is None or purpose_missing:
        b.add(key, "months", "F-SAV-3", t, None)
    elif target - liquid <= 0:
        b.add(key, "months", "F-SAV-3", t, 0)
    elif not funds:
        b.add(key, "months", "F-SAV-3", t, None, "no_emergency_account")
    elif (monthly := t.allocation(funds[0].id)) == 0:
        b.add(key, "months", "F-SAV-3", t, None, "no_allocation")
    elif ceil_div(target - liquid, monthly) > HORIZON_MONTHS:
        b.add(key, "months", "F-SAV-3", t, None, "no_allocation")  # not within 100 years
    else:
        b.add(key, "months", "F-SAV-3", t, ceil_div(target - liquid, monthly))


# --- Debts -------------------------------------------------------------------------------------

_DEBT_FIGURES: Final[tuple[tuple[str, Unit], ...]] = (
    ("debt.strategy_order", "count"),
    ("debt.payoff_months", "months"),
    ("debt.total_interest", "centavos"),
    ("debt.payoff_date", "date"),
)


def _debts(b: _Builder) -> None:
    t = b.trace()
    entities = _open_debts(b, t)
    if entities is None:  # a balance is missing, so which debts are open isn't known
        for e in b.open("debt"):
            for key, unit in _DEBT_FIGURES:
                b.add(key, unit, "F-DEBT-3" if key == "debt.strategy_order" else "F-DEBT-2",
                      t, None, None, e.id)  # fmt: skip
        return
    if not entities:
        return  # nothing is owed: no debt figures
    debts: list[Debt] = []
    reads: dict[uuid.UUID, _Trace] = {}
    complete = True
    for e in entities:
        own = b.trace()
        balance = own.money(e.id, "debt.balance")
        monthly, annual = own.rate(e.id, "debt.monthly_rate"), own.rate(e.id, "debt.annual_rate")
        minimum = own.money(e.id, "debt.minimum_payment")
        extra = own.allocation(e.id)
        reads[e.id] = own
        if monthly is not None and annual is not None:
            raise EngineInputError(f"{e.name} has a monthly and an annual rate; it has one")
        if balance is None or minimum is None or (monthly is None and annual is None):
            complete = False
            continue
        rate = Debt.rate_from(monthly, annual)
        debts.append(Debt(e.id, e.name, balance, rate, minimum, extra))

    strategy: Strategy | None = None
    order_trace = b.trace()
    if len(entities) > 1:
        chosen = order_trace.text(None, "preference.debt_strategy")
        if chosen in ("avalanche", "snowball"):
            strategy = chosen  # type: ignore[assignment]
    for e in entities:  # the order depends on every debt's balance and rate
        order_trace.money(e.id, "debt.balance")
        order_trace.rate(e.id, "debt.monthly_rate")
        order_trace.rate(e.id, "debt.annual_rate")
    ordered: list[Debt] | None = None
    if complete:
        ordered = debts if len(debts) == 1 else None
        if strategy is not None:
            ordered = strategy_order(debts, strategy)

    for e in entities:
        position = None if ordered is None else [d.entity_id for d in ordered].index(e.id) + 1
        flag: Flag | None = None
        if complete and ordered is None:
            flag = "strategy_missing"
        b.add("debt.strategy_order", "count", "F-DEBT-3", order_trace, position, flag, e.id)

    payoffs = simulate(ordered) if ordered is not None else {}
    for e in entities:
        t = b.trace()
        t.use(b.get("debt.strategy_order", e.id))
        flag = b.get("debt.strategy_order", e.id).flag
        payoff = payoffs.get(e.id)
        # The debts are paid off together: a payment freed by any of them can roll to this one.
        for d in ordered if ordered is not None else []:
            t.facts |= reads[d.entity_id].facts
            t.overrides |= reads[d.entity_id].overrides
        t.facts |= reads[e.id].facts
        t.overrides |= reads[e.id].overrides
        months = interest = None
        payoff_date: date | None = None
        if payoff is not None and payoff.months is None:
            flag = "never_pays_off"
        elif payoff is not None and payoff.months is not None:
            months, interest = payoff.months, payoff.total_interest
            payoff_date = add_months(b.inputs.on, payoff.months)
        b.add("debt.payoff_months", "months", "F-DEBT-2", t, months, flag, e.id)
        b.add("debt.total_interest", "centavos", "F-DEBT-2", t, interest, flag, e.id)
        b.add("debt.payoff_date", "date", "F-DEBT-2", t, payoff_date, flag, e.id)


# --- Goals -------------------------------------------------------------------------------------


def _goals(b: _Builder) -> None:
    for g in b.open("goal"):
        t = b.trace()
        target = t.money(g.id, "goal.target_amount")
        saved = t.money(g.id, "goal.saved_amount")
        monthly = t.allocation(g.id)
        months: int | None = None
        flag: Flag | None = None
        if target is not None and saved is not None:
            if target - saved <= 0:
                months = 0
            elif monthly == 0:
                flag = "no_allocation"
            elif ceil_div(target - saved, monthly) > HORIZON_MONTHS:
                flag = "no_allocation"  # too little to get there within 100 years
            else:
                months = ceil_div(target - saved, monthly)
        b.add("goal.months_to_target", "months", "F-GOAL-1", t, months, flag, g.id)
        projected = None if months is None else add_months(b.inputs.on, months)
        b.add("goal.projected_date", "date", "F-GOAL-1", t, projected, flag, g.id)

        t = b.trace()
        target = t.money(g.id, "goal.target_amount")
        saved = t.money(g.id, "goal.saved_amount")
        due = t.day(g.id, "goal.target_date")
        required: int | None = None
        flag = None
        if target is not None and saved is not None and due is not None:
            steps = whole_months_until(b.inputs.on, due)
            if target - saved <= 0:
                required = 0
            elif steps == 0:
                flag = "past_due"
            else:
                required = ceil_div(target - saved, steps)
        b.add("goal.required_monthly", "centavos", "F-GOAL-2", t, required, flag, g.id)

        t = b.trace()
        projected_figure = b.get("goal.projected_date", g.id)
        projected_on = t.use(projected_figure)
        due = t.day(g.id, "goal.target_date")
        on_track: int | None = None
        flag = None
        if isinstance(projected_on, date) and due is not None:
            on_track = 1 if projected_on <= due else 0
        elif projected_figure.flag == "no_allocation" and due is not None:
            on_track, flag = 0, "no_allocation"  # it never gets there
        b.add("goal.on_track", "count", "F-GOAL-3", t, on_track, flag, g.id)


# --- The plan ----------------------------------------------------------------------------------


def _unallocated(b: _Builder) -> None:
    t = b.trace()
    surplus = _int(t.use(b.get("cashflow.monthly_surplus")))
    allocated = sum(
        t.allocation(e.id) for kind in ("debt", "account", "goal") for e in b.open(kind)
    )
    left = None if surplus is None else surplus - allocated
    flag: Flag | None = "negative" if left is not None and left < 0 else None
    b.add("plan.unallocated", "centavos", "F-ALLOC-1", t, left, flag)


def compute(
    snapshot: Snapshot,
    entities: Iterable[EntityRow],
    overrides: Iterable[Override] = (),
) -> Run:
    """Every figure for the household on `snapshot.on`, with a what-if's overrides if any."""
    inputs = Inputs(snapshot, entities, overrides)
    b = _Builder(inputs)
    _cashflow(b)
    _savings(b)
    _debts(b)
    _goals(b)
    _unallocated(b)
    figures = sorted(b.figures.values(), key=lambda f: (f.key, str(f.entity_id or "")))
    return Run(
        household_id=snapshot.household_id,
        as_of=snapshot.on,
        known_at=snapshot.known_at,
        snapshot_hash=snapshot.hash,
        engine_version=ENGINE_VERSION,
        figures=tuple(figures),
    )
