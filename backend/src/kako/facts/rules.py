"""The validation rules over facts (docs/data-model.md, "Validation rules"): V-01 to V-08 and V-16.

The store checks a write before it makes it; `validate` checks a whole household's rows, for the
validation suite (`kako validate`, and CI). Pure: it reads rows it is given.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from kako.facts.attributes import CATALOG, VALUE_COLUMN
from kako.facts.model import EntityRow, FactRow
from kako.facts.snapshot import take_snapshot
from kako.facts.values import FactValueError, check_value


@dataclass(frozen=True)
class Violation:
    rule: str  # "V-01" ...
    table: str
    row_id: uuid.UUID
    message: str

    def __str__(self) -> str:
        return f"{self.rule} {self.table} {self.row_id}: {self.message}"


@dataclass(frozen=True)
class ApprovedRow:
    """A decision or life event, for V-08: the proposal it points at."""

    table: str
    id: uuid.UUID
    proposal_id: uuid.UUID | None


def windows_overlap(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    """Whether two half-open windows [from, to) share a day (a null end is open)."""
    return (a_to is None or b_from < a_to) and (b_to is None or a_from < b_to)


def _v01(fact: FactRow, entities: Mapping[uuid.UUID, EntityRow]) -> str | None:
    attr = CATALOG.get(fact.attribute)
    if attr is None:
        return f"{fact.attribute!r} is not in the attribute catalog"
    set_columns = [column for column in VALUE_COLUMN.values() if getattr(fact, column) is not None]
    if set_columns != [VALUE_COLUMN[attr.value_type]]:
        return f"{fact.attribute} needs only {VALUE_COLUMN[attr.value_type]} set, not {set_columns}"
    if attr.household_wide != (fact.entity_id is None):
        return (
            f"{fact.attribute} is {'household-wide' if attr.household_wide else 'about an entity'}"
        )
    if fact.entity_id is not None:
        entity = entities.get(fact.entity_id)
        if entity is None or entity.kind not in attr.entity_kinds:
            kind = entity.kind if entity else "missing"
            return f"{fact.attribute} doesn't describe a {kind} entity"
    try:
        check_value(attr, fact.value)
    except FactValueError as exc:
        return str(exc)
    return None


def validate(
    facts: Iterable[FactRow],
    entities: Iterable[EntityRow],
    approved_proposal_ids: set[uuid.UUID],
    approved_rows: Iterable[ApprovedRow] = (),
) -> list[Violation]:
    """Every violation of V-01 to V-08 and V-16 in these rows (an empty list: all pass)."""
    rows = list(facts)
    by_id = {f.id: f for f in rows}
    entity_by_id = {e.id: e for e in entities}
    found: list[Violation] = []

    def add(rule: str, fact: FactRow, message: str) -> None:
        found.append(Violation(rule, "fact", fact.id, message))

    live = [f for f in rows if f.status in ("active", "replaced")]
    for fact in rows:
        if (problem := _v01(fact, entity_by_id)) is not None:
            rule = "V-07" if "(V-07)" in problem else "V-01"
            add(rule, fact, problem)

    # V-02: no overlapping windows for one entity and attribute.
    groups: dict[tuple[uuid.UUID, uuid.UUID | None, str], list[FactRow]] = defaultdict(list)
    for fact in live:
        groups[(fact.household_id, fact.entity_id, fact.attribute)].append(fact)
    for group in groups.values():
        group.sort(key=lambda f: (f.valid_from, f.id))
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if windows_overlap(a.valid_from, a.valid_to, b.valid_from, b.valid_to):
                    add("V-02", b, f"{b.attribute} overlaps fact {a.id}")

    proposal_used: dict[uuid.UUID, uuid.UUID] = {}  # a proposal, and the first fact it wrote
    for fact in rows:
        # V-03 and V-04: the replacement chain, both directions, without gaps.
        if fact.replaced_by is not None:
            successor = by_id.get(fact.replaced_by)
            if successor is None or successor.replaces != fact.id:
                add("V-04", fact, f"replaced_by {fact.replaced_by} doesn't point back")
            elif successor.valid_from != fact.valid_to:
                add(
                    "V-03",
                    fact,
                    f"ends {fact.valid_to}, its replacement starts {successor.valid_from}",
                )
            if fact.status != "replaced":
                add("V-04", fact, f"has replaced_by but is {fact.status}")
        if fact.status == "replaced" and fact.replaced_by is None:
            add("V-04", fact, "is replaced but names no replacement")
        if fact.replaces is not None and fact.status != "retracted":
            previous = by_id.get(fact.replaces)
            if previous is None or previous.replaced_by != fact.id:
                add("V-04", fact, f"replaces {fact.replaces}, which doesn't name it back")

        # V-05: a retraction is complete, and no snapshot from then on includes the fact.
        if fact.status == "retracted":
            if fact.retracted_at is None or not (fact.retraction_reason or "").strip():
                add("V-05", fact, "retracted without a time and a reason")
            else:
                later = take_snapshot(fact.household_id, rows, fact.valid_from, fact.retracted_at)
                if fact in later.facts:
                    add("V-05", fact, "still in a snapshot taken after its retraction")
        elif fact.retracted_at is not None or fact.retraction_reason is not None:
            add("V-05", fact, f"has a retraction but is {fact.status}")

        # V-06: inside the entity's life.
        if fact.entity_id is not None and (entity := entity_by_id.get(fact.entity_id)):
            if entity.opened_on is not None and fact.valid_from < entity.opened_on:
                add("V-06", fact, f"starts {fact.valid_from}, before {entity.name} opened")
            if entity.closed_on is not None and fact.valid_from >= entity.closed_on:
                add("V-06", fact, f"starts {fact.valid_from}, after {entity.name} closed")

        # V-08: anything not from the seed came from an approved proposal, its own; the seed
        # has no proposal and replaces nothing.
        if fact.source_kind == "seed":
            if fact.proposal_id is not None or fact.replaces is not None:
                add("V-08", fact, "is from the seed but has a proposal or replaces a fact")
        elif fact.proposal_id not in approved_proposal_ids:
            add("V-08", fact, "is not from the seed and has no approved proposal")
        elif fact.proposal_id in proposal_used:
            add("V-08", fact, f"shares its proposal with {proposal_used[fact.proposal_id]}")
        if fact.proposal_id is not None:
            proposal_used.setdefault(fact.proposal_id, fact.id)

    for row in approved_rows:
        if row.proposal_id not in approved_proposal_ids:
            found.append(Violation("V-08", row.table, row.id, "has no approved proposal"))

    # V-16: at most one emergency fund on any date.
    emergency = [
        f for f in live if f.attribute == "account.purpose" and f.value_text == "emergency"
    ]
    for i, a in enumerate(emergency):
        for b in emergency[i + 1 :]:
            same_household = a.household_id == b.household_id and a.entity_id != b.entity_id
            if same_household and windows_overlap(
                a.valid_from, a.valid_to, b.valid_from, b.valid_to
            ):
                add("V-16", b, f"a second emergency fund while {a.entity_id} is one")
    return found
