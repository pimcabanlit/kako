"""How the plan screen explains a plan, in the household's words (docs/architecture.md, "The plan
screen").

- **Formulas** in plain words: what each formula of docs/data-model.md "Calculations" adds up,
  so "why" on a figure reads as arithmetic, never as a model's say-so.
- **Names**: a figure by its meaning and the thing it is about ("Months until the debt is paid off
  (Credit card)"), a fact by its thing and attribute ("Mara's salary (take-home pay a month)").
- **The number check**: what each number in a text matched, from the check's own match string
  (`figure:<ref>`, `fact:<ref>`, `allocation:<what-if>:<entity>`, `said`), in words.
- **What changed** against the last plan: F-DIFF-1 (`engine.diff`) as rows, the figures that moved
  and the facts behind them.

Pure: no database, Meko or clock. The caller reads the rows (`db.plan_read`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from kako.agents.present import FLAGS, GLOSSARY, day, fact_value, figure_value
from kako.engine.diff import Diff, FactChange, FigureChange
from kako.engine.figures import Figure
from kako.facts.model import EntityRow, FactRow
from kako.upkeep.sentences import PHRASES, subject

# Each formula of docs/data-model.md "Calculations", in plain words. Every formula the engine writes
# has one (tests/test_plan_why.py holds both to the doc).
FORMULAS: Final[dict[str, str]] = {
    "F-INC-1": "The take-home pay of every current income, added up. 13th-month pay is counted "
    "on its own, in December only.",
    "F-EXP-1": "Every monthly expense, added up.",
    "F-EXP-2": "The monthly expenses marked essential, added up.",
    "F-DEBT-1": "The minimum payment of every debt still owed, added up.",
    "F-CF-1": "Take-home pay, less spending, less the minimum debt payments. It can be negative, "
    "and then it says so.",
    "F-CF-2": "The minimum debt payments divided by take-home pay.",
    "F-CF-3": "What the plan puts into savings and goals each month, divided by take-home pay.",
    "F-SAV-1": "The savings you can reach at short notice, divided by essential spending a month.",
    "F-SAV-2": "The household's target in months, times essential spending a month.",
    "F-SAV-3": "What the emergency fund still needs to reach its target, divided by what the plan "
    "puts into it each month, rounded up to whole months.",
    "F-DEBT-2": "The debts paid down together, month by month: each month's interest is added, "
    "then the payment taken off. When a debt is paid off, its whole payment rolls to the next "
    "debt in the payoff order.",
    "F-DEBT-3": "The order freed payments roll in, from the household's payoff strategy: "
    "avalanche (highest interest first) or snowball (smallest balance first).",
    "F-GOAL-1": "What the goal still needs, divided by what the plan puts into it each month, "
    "rounded up to whole months.",
    "F-GOAL-2": "What the goal still needs, divided by the months left until its date.",
    "F-GOAL-3": "On track when the goal is reached by its date at the planned amount.",
    "F-ALLOC-1": "What is left a month, less everything the plan puts on debts, savings and goals.",
}
# The figures "what changed" names first, in this order; any other figure that moved follows.
HEADLINE: Final = (
    "cashflow.monthly_income",
    "cashflow.thirteenth_month",
    "cashflow.monthly_expenses",
    "cashflow.minimum_payments",
    "cashflow.monthly_surplus",
    "plan.unallocated",
    "savings.emergency_runway_months",
    "savings.months_to_target",
    "debt.payoff_months",
    "debt.total_interest",
    "goal.months_to_target",
    "goal.on_track",
)
LABELS: Final[dict[str, str]] = {
    "replaced": "replaced",
    "retracted": "corrected",
    "allocation": "the plan's amount",
    "new": "new",
    "ended": "ended",
}


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def figure_title(key: str, entity: EntityRow | None) -> str:
    """ "Months until the debt is paid off (Credit card)"."""
    meaning = _upper(GLOSSARY.get(key, key))
    return f"{meaning} ({entity.name})" if entity is not None else meaning


def fact_title(fact: FactRow, entity: EntityRow | None) -> str:
    """ "Mara's salary (take-home pay a month)"."""
    return _upper(subject(fact, entity))


def formula_words(formula: str) -> str:
    return FORMULAS.get(formula, formula)


def flag_words(flag: str | None) -> str | None:
    return None if flag is None else FLAGS.get(flag, flag)


# --- The number check, in words -------------------------------------------------------------------


@dataclass(frozen=True)
class Refs:
    """The turn's refs back to names: entities by ref (`debt:credit-card`)."""

    entities: Mapping[str, EntityRow]

    def entity(self, ref: str) -> str:
        found = self.entities.get(ref)
        return found.name if found is not None else ref


def _figure_ref(refs: Refs, text: str) -> str:
    key, _, entity_ref = text.partition("@")
    meaning = _upper(GLOSSARY.get(key, key))
    return f"{meaning} ({refs.entity(entity_ref)})" if entity_ref else meaning


def matched_words(match: str | None, refs: Refs) -> str | None:
    """What a number matched, in words; None when it matched nothing (the check flagged it)."""
    if match is None:
        return None
    kind, _, rest = match.partition(":")
    if kind == "figure":
        # figure:<key>[@<entity>] or figure:<what-if>:<key>[@<entity>]. A what-if's ref
        # (`debt1-W1`) has no dot; a figure key always has one.
        head, _, tail = rest.partition(":")
        if tail and "." not in head:
            return f"{_figure_ref(refs, tail)}, in the option's what-if"
        return _figure_ref(refs, rest)
    if kind == "fact":
        entity_ref, _, attribute = rest.rpartition("/")
        what = PHRASES.get(attribute, attribute)
        if entity_ref:
            return f"{refs.entity(entity_ref)} ({what})"
        return _upper(f"the household's {what}")
    if kind == "allocation":
        _, _, entity_ref = rest.partition(":")
        return f"The option's amount a month for {refs.entity(entity_ref)}"
    if kind == "said":
        return "The household's own words"
    if kind == "date" and rest == "today":
        return "The household's date"
    if kind == "ref":
        return "A reference to the turn's own working"
    return match


# --- What changed against the last plan -----------------------------------------------------------


@dataclass(frozen=True)
class MovedFigure:
    title: str
    before: str
    after: str
    headline: bool


@dataclass(frozen=True)
class ChangedFact:
    label: str  # replaced, corrected, the plan's amount, new, ended
    title: str
    before: str | None
    after: str | None
    from_day: str | None  # when the new value took effect


@dataclass(frozen=True)
class Changes:
    figures: tuple[MovedFigure, ...]
    facts: tuple[ChangedFact, ...]


def _value(figure: Figure | None) -> object:
    return None if figure is None else figure.value


def _shown(figure: Figure | None) -> str:
    return "none" if figure is None else figure_value(figure)


def _fact_of(change: FactChange) -> FactRow:
    fact = change.new or change.old
    if fact is None:
        raise ValueError("a fact change has an old fact or a new one")
    return fact


def changed_fact(change: FactChange, entities: Mapping[uuid.UUID, EntityRow]) -> ChangedFact:
    fact = _fact_of(change)
    entity = entities.get(fact.entity_id) if fact.entity_id else None
    return ChangedFact(
        label=LABELS[change.label],
        title=fact_title(fact, entity),
        before=fact_value(change.old) if change.old is not None else None,
        after=fact_value(change.new) if change.new is not None else None,
        from_day=day(change.new.valid_from) if change.new is not None else None,
    )


def what_changed(diff: Diff, entities: Sequence[EntityRow]) -> Changes:
    """The figures whose value moved, the headline ones first in a fixed order, then the rest by
    name; and the facts behind them. A figure with no value before or after hasn't moved."""
    by_id = {e.id: e for e in entities}
    rank = {key: n for n, key in enumerate(HEADLINE)}
    moved: list[tuple[tuple[int, str], FigureChange]] = []
    for change in diff.figures:
        if _value(change.old) == _value(change.new):
            continue
        entity = by_id.get(change.ref.entity_id) if change.ref.entity_id else None
        title = figure_title(change.ref.key, entity)
        moved.append(((rank.get(change.ref.key, len(rank)), title), change))
    moved.sort(key=lambda item: item[0])
    figures = tuple(
        MovedFigure(
            title=figure_title(c.ref.key, by_id.get(c.ref.entity_id) if c.ref.entity_id else None),
            before=_shown(c.old),
            after=_shown(c.new),
            headline=c.ref.key in rank,
        )
        for _, c in moved
    )
    facts = tuple(changed_fact(f, by_id) for f in diff.fact_changes)
    return Changes(figures, facts)
