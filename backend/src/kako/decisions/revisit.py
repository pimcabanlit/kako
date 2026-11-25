"""Which decisions to revisit as Kako knows the household now (the decisions screen).

A decision rests on facts (`decision_assumption`, see `assumptions.py`). Once one of them has been
replaced or retracted, the ground under the decision has moved, and the household is asked to look
at it again. The replan (F-DIFF-1, `engine.diff`) asks the same on a plan's date; this asks it of
everything Kako knows, so a change that takes effect later (a new job from Dec 1) is already listed,
with the day it takes effect.

Pure: the caller passes the facts, in every status.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping

from kako.engine.diff import FactChange
from kako.facts.model import FactRow


def now_of(fact: FactRow, by_id: Mapping[uuid.UUID, FactRow]) -> FactRow | None:
    """What stands in a fact's place now: the end of its replacement chain, or, for a retracted
    fact, the one it had replaced (back in force). None when nothing does."""
    if fact.status == "retracted":
        back = by_id.get(fact.replaces) if fact.replaces else None
        return back if back is not None and back.status != "retracted" else None
    current, seen = fact, {fact.id}
    while current.replaced_by is not None and current.replaced_by not in seen:
        nxt = by_id.get(current.replaced_by)
        if nxt is None:
            break
        seen.add(nxt.id)
        current = nxt
    return current if current.id != fact.id else None


def _id(fact: FactRow | None) -> uuid.UUID | None:
    return None if fact is None else fact.id


def to_revisit(
    assumed: Mapping[uuid.UUID, Iterable[uuid.UUID]], facts: Iterable[FactRow]
) -> dict[uuid.UUID, tuple[FactChange, ...]]:
    """Each decision whose facts have moved, with the changes: a fact replaced (by the latest value
    in its chain) or retracted (with the value back in force, if any). A decision none of whose
    facts moved is left out. A fact a decision names must be given."""
    by_id = {f.id: f for f in facts}
    found: dict[uuid.UUID, tuple[FactChange, ...]] = {}
    for decision_id, fact_ids in assumed.items():
        changes: list[FactChange] = []
        for fact_id in sorted(set(fact_ids), key=str):
            fact = by_id.get(fact_id)
            if fact is None:
                raise ValueError(
                    f"decision {decision_id} rests on fact {fact_id}, which isn't given"
                )
            if fact.status == "retracted":
                changes.append(FactChange("retracted", fact, now_of(fact, by_id)))
            elif fact.status == "replaced":
                changes.append(FactChange("replaced", fact, now_of(fact, by_id)))
        if changes:
            found[decision_id] = tuple(
                sorted(changes, key=lambda c: (c.attribute, str(c.entity_id), str(_id(c.old))))
            )
    return found
