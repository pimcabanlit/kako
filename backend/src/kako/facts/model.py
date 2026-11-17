"""Plain values for facts, shared by the snapshot, the rules and the store (no database types)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

FactValue = int | Decimal | date | str
Status = Literal["active", "replaced", "retracted"]
SourceKind = Literal["seed", "session", "statement", "household_entry", "dreaming"]


@dataclass(frozen=True)
class FactRow:
    """One row of the `fact` table, as stored."""

    id: uuid.UUID
    household_id: uuid.UUID
    entity_id: uuid.UUID | None
    attribute: str
    value_money: int | None
    value_rate: Decimal | None
    value_int: int | None
    value_date: date | None
    value_text: str | None
    valid_from: date
    valid_to: date | None
    replaces: uuid.UUID | None
    replaced_by: uuid.UUID | None
    status: Status
    recorded_at: datetime
    retracted_at: datetime | None
    retraction_reason: str | None
    source_kind: SourceKind
    source_ref: str
    proposal_id: uuid.UUID | None
    life_event_id: uuid.UUID | None

    @property
    def value(self) -> FactValue:
        """The one value that is set (V-01 makes sure there is exactly one)."""
        for value in (
            self.value_money,
            self.value_rate,
            self.value_int,
            self.value_date,
            self.value_text,
        ):
            if value is not None:
                return value
        raise ValueError(f"fact {self.id} has no value")


@dataclass(frozen=True)
class EntityRow:
    """The parts of an `entity` row the rules read."""

    id: uuid.UUID
    household_id: uuid.UUID
    kind: str
    name: str
    opened_on: date | None
    closed_on: date | None
