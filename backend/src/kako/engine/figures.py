"""A figure: one number the engine produced, with the facts and figures it was built from."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

# The values of figure.unit and figure.flag (docs/data-model.md, `figure`; kako.db.enums).
Unit = Literal["centavos", "months", "ratio", "date", "count"]
Flag = Literal[
    "never_pays_off",
    "no_allocation",
    "no_emergency_account",
    "strategy_missing",
    "past_due",
    "negative",
    "no_income",
    "no_essential_expenses",
    "missing_input",
]
FigureValue = int | Decimal | date


@dataclass(frozen=True, order=True)
class FigureRef:
    """A figure by its key and the entity it is about (None: the household)."""

    key: str
    entity_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Figure:
    key: str
    entity_id: uuid.UUID | None
    unit: Unit
    value: FigureValue | None  # None only with a flag that says why
    flag: Flag | None
    formula: str  # the formula id, such as F-CF-1
    input_fact_ids: tuple[uuid.UUID, ...]  # sorted
    input_override_ids: tuple[uuid.UUID, ...]  # a what-if's hypothetical values, sorted
    input_figures: tuple[FigureRef, ...]  # sorted

    def __post_init__(self) -> None:
        if self.value is None and self.flag is None:
            raise ValueError(f"figure {self.key} has no value and no flag")

    @property
    def ref(self) -> FigureRef:
        return FigureRef(self.key, self.entity_id)


@dataclass(frozen=True)
class Run:
    """Every figure for one snapshot (and, for a what-if, its overrides)."""

    household_id: uuid.UUID
    as_of: date
    snapshot_hash: str
    engine_version: str
    figures: tuple[Figure, ...]

    def get(self, key: str, entity_id: uuid.UUID | None = None) -> Figure:
        for figure in self.figures:
            if figure.key == key and figure.entity_id == entity_id:
                return figure
        raise KeyError(f"no figure {key} for {entity_id}")

    def value(self, key: str, entity_id: uuid.UUID | None = None) -> FigureValue | None:
        return self.get(key, entity_id).value
