"""What the engine reads: a snapshot's facts, the household's entities, and a what-if's overrides.

A what-if (`scenario_override`) is a hypothetical value in the shape of a fact. It takes the place
of the snapshot's value for the same entity and attribute and is never written to `fact`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from kako.facts.attributes import attribute
from kako.facts.model import EntityRow, FactValue
from kako.facts.snapshot import Snapshot
from kako.facts.values import FactValueError, check_value


class EngineInputError(ValueError):
    """Input the engine can't read without guessing: rows that contradict each other."""


@dataclass(frozen=True)
class Override:
    """One hypothetical value of a what-if (a `scenario_override` row)."""

    id: uuid.UUID
    entity_id: uuid.UUID | None
    attribute: str
    value: FactValue
    valid_from: date


@dataclass(frozen=True)
class Value:
    """A value the engine read, and where it came from: a fact or an override."""

    value: FactValue
    fact_id: uuid.UUID | None = None
    override_id: uuid.UUID | None = None


class Inputs:
    """The snapshot as the formulas read it: one value per entity and attribute."""

    def __init__(
        self,
        snapshot: Snapshot,
        entities: Iterable[EntityRow],
        overrides: Iterable[Override] = (),
    ) -> None:
        self.on = snapshot.on
        self.household_id = snapshot.household_id
        self.entities = {e.id: e for e in entities}
        for entity in self.entities.values():
            if entity.household_id != self.household_id:
                raise EngineInputError(f"entity {entity.name} isn't this household's")
        self._values: dict[tuple[uuid.UUID | None, str], Value] = {}
        for fact in snapshot.facts:
            if fact.household_id != self.household_id:
                raise EngineInputError(f"fact {fact.id} isn't this household's")
            if fact.entity_id is not None and fact.entity_id not in self.entities:
                raise EngineInputError(f"fact {fact.id} is about an entity the engine wasn't given")
            key = (fact.entity_id, fact.attribute)
            if key in self._values:
                raise EngineInputError(f"two values for {fact.attribute} on {self.on} (V-02)")
            self._values[key] = Value(fact.value, fact_id=fact.id)
        seen: set[tuple[uuid.UUID | None, str]] = set()
        for override in overrides:
            key = (override.entity_id, override.attribute)
            if key in seen:
                raise EngineInputError(f"two what-if values for {override.attribute}")
            seen.add(key)
            try:
                check_value(attribute(override.attribute), override.value)
            except (KeyError, FactValueError) as exc:
                raise EngineInputError(f"what-if value: {exc}") from exc
            if override.entity_id is not None and override.entity_id not in self.entities:
                raise EngineInputError(f"what-if {override.id} is about an unknown entity")
            if override.valid_from <= self.on:
                self._values[key] = Value(override.value, override_id=override.id)

    def is_open(self, entity: EntityRow) -> bool:
        """Open on the as-of date: opened by then and not yet closed (closed_on is exclusive)."""
        opened = entity.opened_on is None or entity.opened_on <= self.on
        return opened and (entity.closed_on is None or self.on < entity.closed_on)

    def open_entities(self, kind: str) -> list[EntityRow]:
        """The open entities of one kind, in a fixed order (name, then id)."""
        found = [e for e in self.entities.values() if e.kind == kind and self.is_open(e)]
        return sorted(found, key=lambda e: (e.name, str(e.id)))

    def get(self, entity_id: uuid.UUID | None, attribute_key: str) -> Value | None:
        return self._values.get((entity_id, attribute_key))
