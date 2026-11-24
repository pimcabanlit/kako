"""The one sentence Kako keeps in Meko for a fact (docs/data-model.md, "What Kako keeps in Meko").

Pure: no database, Meko or clock. A sentence names the household and the thing in full, because
Meko's search boosts named entities, and carries the dates in its words, because Meko keeps a
memory's metadata on update but can't change it. A fact in force reads in the present tense; a
replaced one in the past tense, with the day it ended ("until Nov 30, 2026"); a retracted fact has
no sentence: its memory is deleted. Memories are context for agents, never the source of a number:
figures come from the engine.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from kako.agents.present import day, fact_value
from kako.facts.model import EntityRow, FactRow

# What each attribute is, in plain words, after the thing it describes.
PHRASES: Final[dict[str, str]] = {
    "income.monthly_net": "take-home pay a month",
    "income.thirteenth_month": "13th-month pay",
    "income.pay_day": "pay day (day of the month)",
    "expense.monthly_amount": "amount a month",
    "expense.essential": "essential (yes or no)",
    "debt.balance": "balance",
    "debt.monthly_rate": "interest rate",
    "debt.annual_rate": "interest rate",
    "debt.minimum_payment": "minimum payment a month",
    "account.balance": "balance",
    "account.liquid": "available at short notice (yes or no)",
    "account.purpose": "purpose",
    "goal.target_amount": "target amount",
    "goal.target_date": "target date",
    "goal.saved_amount": "amount saved",
    "goal.priority": "priority among goals (1 is first)",
    "plan.allocation": "planned amount a month",
    "household.emergency_months_target": "emergency fund target, in months of essential spending",
    "preference.debt_vs_flexibility": (
        "preference between paying debt off faster (speed) and keeping cash on hand (flexibility)"
    ),
    "preference.debt_strategy": "debt payoff strategy",
    "preference.note": "preference, in its own words",
    "constraint.note": "constraint, in its own words",
}


def subject(fact: FactRow, entity: EntityRow | None) -> str:
    """What the fact is about, in words: "Mara's salary (take-home pay a month)"."""
    phrase = PHRASES.get(fact.attribute, fact.attribute)
    return f"{entity.name} ({phrase})" if entity is not None else f"the household's {phrase}"


def fact_sentence(fact: FactRow, household: str, entity: EntityRow | None) -> str | None:
    """The fact as one sentence, or None for a retracted fact (Meko must not find it again).
    A preference shared in collective memory is its sentence while in force, kept as it was."""
    if fact.status == "retracted":
        return None
    subject_ = subject(fact, entity)
    value = fact_value(fact)
    if fact.status == "replaced" and fact.valid_to is not None:
        until = fact.valid_to - timedelta(days=1)  # valid_to is the replacement's first day
        return (
            f"In the {household}, from {day(fact.valid_from)} until {day(until)}, "
            f"{subject_} was {value}."
        )
    return f"In the {household}, from {day(fact.valid_from)}, {subject_} is {value}."
