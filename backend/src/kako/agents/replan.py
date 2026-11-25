"""The replan after a life event (docs/architecture.md, "How a life event replans", steps 3 to 5).

Once the household approves a change it stated in a session (a life event and its facts, or facts
alone), the session's next turns are a **replan**: as of the date the change takes effect, compared
with the plan the household last decided on. Code works out what the change touches, never a model:

- **what changed**: F-DIFF-1 (`engine.diff`) between the run the household last decided on (its
  latest decision, on the decision's date as Kako knew it then; or, with no decision, this session
  before its changes) and the turn's run: each figure that moved, old and new, and the facts behind
  it, labelled replaced, retracted, allocation, new or ended;
- **to revisit**: the active decisions whose assumptions (`decision_assumption`) were replaced or
  retracted.

The agents read both in the brief, the orchestrator asks the specialists whose figures moved to
reassess, and the answer has three parts: the new plan (the reply and its options), what changed
(written here, from the diff) and why (the orchestrator's reason, checked like any text, with the
facts and decisions written here). Pure: the caller gathers the rows (`agents.replan_store`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from kako.agents.present import GLOSSARY, Refs, day, fact_value, figure_value
from kako.engine.diff import Diff, FactChange, FigureChange
from kako.engine.figures import Figure, Run
from kako.facts.model import EntityRow, FactRow
from kako.upkeep.sentences import subject

# The figures a replan names, in this order; any other figure that moved is counted, not listed.
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
# Which specialist reads which figures: the ones whose figures moved are asked to reassess.
AREAS: Final = {"cashflow": "budget", "plan": "budget", "savings": "savings", "debt": "debt"}
AREAS_GOAL: Final = "goals"


@dataclass(frozen=True)
class Revisit:
    """An active decision whose assumptions changed: the household may want to decide again."""

    decision_id: uuid.UUID
    question: str
    chosen: str
    session_title: str
    decided_on: str  # its date, written out
    facts: tuple[FactChange, ...]


@dataclass(frozen=True)
class Replan:
    since: str  # what the turn is compared with, in plain words
    since_decision: uuid.UUID | None  # the decision it is compared with, if any
    before: Run  # the run the household last decided on
    diff: Diff  # from `before` to the turn's run
    revisit: tuple[Revisit, ...]

    @property
    def moved(self) -> tuple[FigureChange, ...]:
        """The figures whose value moved: a figure that has none before or after (a goal whose
        facts don't exist yet) hasn't moved."""
        return tuple(c for c in self.diff.figures if _value(c.old) != _value(c.new))

    @property
    def areas(self) -> tuple[str, ...]:
        """The specialists whose figures moved, in a fixed order."""
        found = set()
        for change in self.moved:
            head = change.ref.key.partition(".")[0]
            found.add(AREAS.get(head, AREAS_GOAL if head == "goal" else "budget"))
        return tuple(a for a in ("budget", "debt", "savings", "goals") if a in found)


def _value(figure: Figure | None) -> object:
    return None if figure is None else figure.value


def _headline(replan: Replan) -> list[FigureChange]:
    rank = {key: n for n, key in enumerate(HEADLINE)}
    return sorted(
        (c for c in replan.moved if c.ref.key in rank),
        key=lambda c: (rank[c.ref.key], str(c.ref.entity_id)),
    )


def _fact_of(change: FactChange) -> FactRow:
    """The fact a change is about: the new one, or the old one when nothing took its place."""
    fact = change.new or change.old
    if fact is None:
        raise ValueError("a fact change has an old fact or a new one")
    return fact


def _figure_of(change: FigureChange) -> Figure:
    figure = change.new or change.old
    if figure is None:
        raise ValueError("a figure change has an old figure or a new one")
    return figure


def _was(change: FigureChange) -> str:
    return "none" if change.old is None else figure_value(change.old)


def _now(change: FigureChange) -> str:
    return "none" if change.new is None else figure_value(change.new)


def _fact_line(change: FactChange, name: str) -> str:
    old, new = change.old, change.new
    if change.label in ("replaced", "allocation") and old is not None and new is not None:
        return (
            f"{name}: {fact_value(old)} → {fact_value(new)} from {day(new.valid_from)} "
            f"({change.label})"
        )
    if change.label == "retracted" and old is not None:
        back = f"; {fact_value(new)} is back" if new is not None else ""
        return f"{name}: {fact_value(old)} retracted as a mistake{back}"
    if new is not None:
        return f"{name}: {fact_value(new)} from {day(new.valid_from)} ({change.label})"
    old = _fact_of(change)
    return f"{name}: {fact_value(old)} ended {day(old.valid_to or old.valid_from)}"


def _named(fact: FactRow, entities: dict[uuid.UUID, EntityRow]) -> str:
    """A fact by name and in words, as the household reads it: "Mara's salary (take-home pay a
    month)", never the attribute's key."""
    return subject(fact, entities.get(fact.entity_id) if fact.entity_id else None)


def brief_lines(replan: Replan, refs: Refs, decisions: dict[uuid.UUID, str]) -> list[str]:
    """The replan as the agents read it in the brief: refs they can cite, old and new values."""
    lines = [f"Compared with {replan.since}. Figures before → now:"]
    for change in _headline(replan):
        figure = _figure_of(change)
        lines.append(f"- {refs.figure(figure)}: {_was(change)} → {_now(change)}")
    others = len(replan.moved) - len(_headline(replan))
    if others:
        lines.append(f"- and {others} more figures (read them with get_figures)")
    lines.append("Facts behind the changes:")
    for fact in replan.diff.fact_changes:
        lines.append(f"- {_fact_line(fact, 'fact:' + refs.fact(_fact_of(fact)))}")
    if not replan.diff.fact_changes:
        lines.append("- None.")
    lines.append("Decisions to revisit (an assumption changed):")
    for revisit in replan.revisit:
        rested = "; ".join(_fact_line(f, "fact:" + refs.fact(_fact_of(f))) for f in revisit.facts)
        lines.append(f"- {decisions.get(revisit.decision_id, 'a decision')}: rested on {rested}")
    if not replan.revisit:
        lines.append("- None.")
    lines.append("Specialists whose figures moved: " + (", ".join(replan.areas) or "none"))
    return lines


def changes_lines(replan: Replan, entities: tuple[EntityRow, ...]) -> list[str]:
    """What changed, as the household reads it: figures by their meaning, facts by name."""
    names = {e.id: e.name for e in entities}
    lines = [f"What changed since {replan.since}:"]
    for change in _headline(replan):
        meaning = GLOSSARY.get(change.ref.key, change.ref.key)
        about = f" ({names[change.ref.entity_id]})" if change.ref.entity_id in names else ""
        lines.append(f"- {meaning[0].upper()}{meaning[1:]}{about}: {_was(change)} → {_now(change)}")
    return lines


def why_lines(replan: Replan, entities: tuple[EntityRow, ...]) -> list[str]:
    """The facts behind the change and the decisions to revisit, as the household reads them."""
    names = {e.id: e for e in entities}
    lines = ["Because:"]
    for fact in replan.diff.fact_changes:
        lines.append(f"- {_fact_line(fact, _named(_fact_of(fact), names))}")
    for revisit in replan.revisit:
        rested = "; ".join(_fact_line(f, _named(_fact_of(f), names)) for f in revisit.facts)
        lines.append(
            f"- To revisit: “{revisit.question}” ({revisit.session_title}, "
            f"{revisit.decided_on}: chose {revisit.chosen}) rested on {rested}"
        )
    return lines
