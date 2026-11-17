"""F-DIFF-1: what changed between two runs, and why, and the decisions to revisit.

Two runs are compared figure by figure. Each figure that changed (its value or its flag, or it
exists in only one run) lists the facts behind the change: the facts it was built from, directly or
through the figures it read, that differ between the two runs. Each fact change has a label:

- `replaced`: life changed. A newer fact took the old one's place (a new job, a new statement).
- `retracted`: a mistake was fixed. The old fact was retracted, and the one it had replaced is
  back.
- `allocation`: the household chose differently (`plan.allocation`, replaced or new).
- `new`: a fact that started, or that Kako learned, after the old run.
- `ended`: a fact the old run read whose window has closed with nothing in its place.

A fact the new run reads that was already true and known at the old run (13th-month pay, read only
in December) is not a change, so it isn't listed.

A decision rests on facts (`decision_assumption`). When one of them has been replaced or retracted
by the new run's date, the decision is listed **to revisit**.

Pure: the caller passes the household's facts, in every status.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from kako.engine.figures import Figure, FigureRef, Run
from kako.facts.model import FactRow
from kako.facts.snapshot import take_snapshot

Label = Literal["replaced", "retracted", "allocation", "new", "ended"]


@dataclass(frozen=True)
class FactChange:
    label: Label
    old: FactRow | None  # the fact the old run read (None: nothing was there)
    new: FactRow | None  # the fact the new run reads in its place (None: nothing is)

    @property
    def entity_id(self) -> uuid.UUID | None:
        return (self.new or self.old).entity_id  # type: ignore[union-attr]

    @property
    def attribute(self) -> str:
        return (self.new or self.old).attribute  # type: ignore[union-attr]


@dataclass(frozen=True)
class FigureChange:
    ref: FigureRef
    old: Figure | None  # None: the figure is new
    new: Figure | None  # None: the figure is gone
    facts: tuple[FactChange, ...]


@dataclass(frozen=True)
class ToRevisit:
    decision_id: uuid.UUID
    facts: tuple[FactChange, ...]


@dataclass(frozen=True)
class Diff:
    figures: tuple[FigureChange, ...]
    decisions: tuple[ToRevisit, ...] = ()

    def get(self, key: str, entity_id: uuid.UUID | None = None) -> FigureChange | None:
        for change in self.figures:
            if change.ref == FigureRef(key, entity_id):
                return change
        return None

    @property
    def fact_changes(self) -> tuple[FactChange, ...]:
        """Every fact change behind any figure, once each."""
        seen: dict[tuple[uuid.UUID | None, uuid.UUID | None], FactChange] = {}
        for change in self.figures:
            for fact in change.facts:
                key = (fact.old.id if fact.old else None, fact.new.id if fact.new else None)
                seen.setdefault(key, fact)
        return tuple(sorted(seen.values(), key=_change_order))


def _change_order(change: FactChange) -> tuple[str, str, str, str]:
    old, new = change.old, change.new
    return (
        change.attribute,
        str(change.entity_id),
        str(old.id if old else ""),
        str(new.id if new else ""),
    )


def _closures(run: Run) -> dict[FigureRef, frozenset[uuid.UUID]]:
    """Each figure's facts: its own, and those of every figure it was built from."""
    by_ref = {f.ref: f for f in run.figures}
    done: dict[FigureRef, frozenset[uuid.UUID]] = {}

    def closure(ref: FigureRef, path: frozenset[FigureRef]) -> frozenset[uuid.UUID]:
        if ref in done:
            return done[ref]
        if ref in path:
            raise ValueError(f"figure {ref.key} is built from itself")
        figure = by_ref.get(ref)
        if figure is None:
            return frozenset()
        found = set(figure.input_fact_ids)
        for parent in figure.input_figures:
            found |= closure(parent, path | {ref})
        done[ref] = frozenset(found)
        return done[ref]

    for ref in by_ref:
        closure(ref, frozenset())
    return done


def _retracted_by(fact: FactRow, known_at: datetime | None) -> bool:
    if fact.retracted_at is None:
        return False
    return known_at is None or fact.retracted_at <= known_at


def _fact_changes(
    old_ids: frozenset[uuid.UUID],
    new_ids: frozenset[uuid.UUID],
    by_id: Mapping[uuid.UUID, FactRow],
    old_run: Run,
    new_run: Run,
) -> tuple[FactChange, ...]:
    removed, added = set(old_ids - new_ids), set(new_ids - old_ids)
    changes: list[FactChange] = []
    for fact_id in sorted(added, key=str):
        new = by_id[fact_id]
        step: uuid.UUID | None = new.replaces
        seen: set[uuid.UUID] = set()
        while step is not None and step not in removed and step not in seen:
            seen.add(step)
            step = by_id[step].replaces if step in by_id else None
        if step is not None and step in removed:
            removed.discard(step)
            added.discard(fact_id)
            label: Label = "allocation" if new.attribute == "plan.allocation" else "replaced"
            changes.append(FactChange(label, by_id[step], new))
    for fact_id in sorted(removed, key=str):
        old = by_id[fact_id]
        if _retracted_by(old, new_run.known_at):
            back = old.replaces if old.replaces in added else None
            if back is not None:
                added.discard(back)
            changes.append(FactChange("retracted", old, by_id[back] if back else None))
        elif old.valid_to is not None and old.valid_to <= new_run.as_of:
            changes.append(FactChange("ended", old, None))
    for fact_id in sorted(added, key=str):
        new = by_id[fact_id]
        if new.attribute == "plan.allocation":
            changes.append(FactChange("allocation", None, new))
        elif new.valid_from > old_run.as_of or (
            old_run.known_at is not None and new.recorded_at > old_run.known_at
        ):
            changes.append(FactChange("new", None, new))
    return tuple(sorted(changes, key=_change_order))


def diff(
    old: Run,
    new: Run,
    facts: Iterable[FactRow],
    assumptions: Mapping[uuid.UUID, Iterable[uuid.UUID]] | None = None,
) -> Diff:
    """What changed from `old` to `new`. `facts`: the household's facts, in every status.
    `assumptions`: each decision and the facts it rested on (`decision_assumption`)."""
    if old.household_id != new.household_id:
        raise ValueError("a diff compares two runs of the same household")
    rows = list(facts)
    if any(f.household_id != new.household_id for f in rows):
        raise ValueError("a diff reads only its own household's facts")
    by_id = {f.id: f for f in rows}
    old_figures = {f.ref: f for f in old.figures}
    new_figures = {f.ref: f for f in new.figures}
    old_closure, new_closure = _closures(old), _closures(new)
    changed: list[FigureChange] = []
    for ref in sorted(
        old_figures.keys() | new_figures.keys(), key=lambda r: (r.key, str(r.entity_id))
    ):
        a, b = old_figures.get(ref), new_figures.get(ref)
        if a is not None and b is not None and (a.value, a.flag) == (b.value, b.flag):
            continue
        fact_changes = _fact_changes(
            old_closure.get(ref, frozenset()), new_closure.get(ref, frozenset()), by_id, old, new
        )
        changed.append(FigureChange(ref, a, b, fact_changes))
    return Diff(tuple(changed), _to_revisit(assumptions or {}, rows, new))


def _to_revisit(
    assumptions: Mapping[uuid.UUID, Iterable[uuid.UUID]], rows: list[FactRow], new: Run
) -> tuple[ToRevisit, ...]:
    by_id = {f.id: f for f in rows}
    current = take_snapshot(new.household_id, rows, new.as_of, new.known_at)
    found: list[ToRevisit] = []
    for decision_id in sorted(assumptions, key=str):
        changes: list[FactChange] = []
        for fact_id in sorted(set(assumptions[decision_id]), key=str):
            fact = by_id.get(fact_id)
            if fact is None:
                raise ValueError(
                    f"decision {decision_id} rests on fact {fact_id}, which isn't given"
                )
            now = current.get(fact.entity_id, fact.attribute)
            if now is not None and now.id == fact.id:
                continue  # still what the household's life rests on
            if _retracted_by(fact, new.known_at):
                changes.append(FactChange("retracted", fact, now))
            elif fact.replaced_by is not None:
                changes.append(FactChange("replaced", fact, now))
            # Otherwise its window simply hasn't started or has ended: nothing to revisit.
        if changes:
            found.append(ToRevisit(decision_id, tuple(sorted(changes, key=_change_order))))
    return tuple(found)


__all__ = ["Diff", "FactChange", "FigureChange", "Label", "ToRevisit", "diff"]
