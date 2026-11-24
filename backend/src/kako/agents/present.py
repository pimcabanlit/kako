"""How the agents see the household: stable short references and figures written out in words.

Agents never see database ids. Each entity has a **ref** built from its kind and name
(`debt:credit-card`), stable on any machine and readable; a figure is cited as `<key>` or
`<key>@<entity ref>`, a fact as `<entity ref>/<attribute>` (or the attribute alone for a
household-wide fact). Code maps refs back to ids, so a recorded turn replays anywhere and a model
can't make up an id.

Values are written the way the household reads them and the way an agent should copy them:
₱9,050.00; 12 months; 2.1 months; 15.0%; Feb 15, 2028. Pure: no database, Meko or clock.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from kako.engine.figures import Figure
from kako.facts.model import EntityRow, FactRow

KIND_ORDER: Final = ("income", "expense", "debt", "account", "goal")

# What each figure means, in plain words: for prompts and for the brief.
GLOSSARY: Final[dict[str, str]] = {
    "cashflow.monthly_income": "take-home pay a month, all incomes",
    "cashflow.thirteenth_month": "13th-month pay this December",
    "cashflow.monthly_expenses": "spending a month",
    "cashflow.essential_expenses": "essential spending a month",
    "cashflow.minimum_payments": "minimum debt payments a month",
    "cashflow.monthly_surplus": "what is left a month after spending and minimum payments",
    "cashflow.debt_payment_share": "minimum payments as a share of income",
    "cashflow.savings_rate": "allocations to savings and goals as a share of income",
    "savings.emergency_runway_months": "months of essential spending the liquid savings cover",
    "savings.emergency_target": "the emergency fund's target",
    "savings.months_to_target": "months until the emergency fund reaches its target",
    "debt.strategy_order": "the debt's place in the payoff order (1 is first)",
    "debt.payoff_months": "months until the debt is paid off",
    "debt.total_interest": "interest paid on the debt until it is paid off",
    "debt.payoff_date": "when the debt is paid off",
    "goal.months_to_target": "months until the goal is reached",
    "goal.projected_date": "when the goal is reached",
    "goal.required_monthly": "a month needed to reach the goal by its date",
    "goal.on_track": "1 if the goal is on track for its date, else 0",
    "plan.unallocated": "surplus not yet allocated a month",
}
FLAGS: Final[dict[str, str]] = {
    "never_pays_off": "never paid off at this payment",
    "no_allocation": "nothing allocated to it",
    "no_emergency_account": "no account is the emergency fund",
    "strategy_missing": "no payoff strategy chosen",
    "past_due": "its date has passed",
    "negative": "negative",
    "no_income": "no income to divide by",
    "no_essential_expenses": "no essential spending to divide by",
    "missing_input": "a fact it needs is missing",
}


def money(centavos: int) -> str:
    """₱9,050.00; a negative amount as -₱1,200.00."""
    sign = "-" if centavos < 0 else ""
    pesos, cents = divmod(abs(centavos), 100)
    return f"{sign}₱{pesos:,}.{cents:02d}"


def day(value: date) -> str:
    """Feb 15, 2028."""
    return f"{value:%b} {value.day}, {value.year}"


def _one_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def months(count: int) -> str:
    return f"{count} month" if count == 1 else f"{count} months"


def figure_value(figure: Figure) -> str:
    """The figure's value in words, or why it has none."""
    if figure.value is None:
        return f"none ({FLAGS.get(figure.flag or '', figure.flag or 'no value')})"
    value = figure.value
    if isinstance(value, date):
        text = day(value)
    elif figure.unit == "centavos" and isinstance(value, int):
        text = money(value)
    elif figure.unit == "months" and isinstance(value, int):
        text = months(value)
    elif figure.unit == "ratio" and isinstance(value, Decimal):
        if figure.key.endswith("_months"):
            text = f"{_one_decimal(value)} months"
        else:
            text = f"{_one_decimal(value * 100)}%"
    else:
        text = str(value)
    return f"{text} ({FLAGS[figure.flag]})" if figure.flag else text


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unnamed"


@dataclass(frozen=True)
class Refs:
    """Stable refs for one household's entities, both ways."""

    by_id: dict[uuid.UUID, str]
    by_ref: dict[str, uuid.UUID]

    @classmethod
    def of(cls, entities: Iterable[EntityRow]) -> Refs:
        by_id: dict[uuid.UUID, str] = {}
        for e in sorted(entities, key=lambda e: (_kind_rank(e.kind), e.name, str(e.id))):
            ref = base = f"{e.kind}:{slug(e.name)}"
            n = 2
            while ref in by_id.values():  # two names that slug the same: Car loan, Car-loan
                ref, n = f"{base}-{n}", n + 1
            by_id[e.id] = ref
        return cls(by_id, {ref: entity_id for entity_id, ref in by_id.items()})

    def entity(self, entity_id: uuid.UUID | None) -> str | None:
        return None if entity_id is None else self.by_id[entity_id]

    def figure(self, figure: Figure) -> str:
        """`debt.payoff_months@debt:credit-card`, or the key alone for a household figure."""
        ref = self.entity(figure.entity_id)
        return figure.key if ref is None else f"{figure.key}@{ref}"

    def fact(self, fact: FactRow) -> str:
        """`debt:credit-card/debt.balance`, or the attribute alone for a household-wide fact."""
        ref = self.entity(fact.entity_id)
        return fact.attribute if ref is None else f"{ref}/{fact.attribute}"


def _kind_rank(kind: str) -> int:
    return KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)


def fact_value(fact: FactRow) -> str:
    """A fact's value in words: money as pesos, a rate as a percentage, a date in full."""
    value = fact.value
    if fact.value_money is not None:
        return money(fact.value_money)
    if fact.value_rate is not None:
        percent = (fact.value_rate * 100).normalize()
        period = "a month" if fact.attribute.endswith("monthly_rate") else "a year"
        return f"{percent:f}% {period}"
    if isinstance(value, date):
        return day(value)
    return str(value)
