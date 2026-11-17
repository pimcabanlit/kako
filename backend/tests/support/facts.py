"""Builders for fact rows in pure tests (no database)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from kako.facts.model import EntityRow, FactRow

HOUSEHOLD = uuid.UUID("00000000-0000-4000-8000-000000000001")


def at(day: str, hour: int = 9) -> datetime:
    """A UTC time on an ISO day, for recorded_at and known_at."""
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


def entity(kind: str = "income", name: str = "Ana's salary", **fields: Any) -> EntityRow:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "household_id": HOUSEHOLD,
        "kind": kind,
        "name": name,
        "opened_on": None,
        "closed_on": None,
    }
    values.update(fields)
    return EntityRow(**values)


def fact(
    entity_id: uuid.UUID | None,
    attribute: str,
    value: int | Decimal | date | str,
    valid_from: str,
    **fields: Any,
) -> FactRow:
    columns: dict[str, Any] = dict.fromkeys(
        ("value_money", "value_rate", "value_int", "value_date", "value_text")
    )
    if isinstance(value, Decimal):
        columns["value_rate"] = value
    elif isinstance(value, date):
        columns["value_date"] = value
    elif isinstance(value, str):
        columns["value_text"] = value
    elif attribute.endswith(("pay_day", "priority", "months_target")):
        columns["value_int"] = value
    else:
        columns["value_money"] = value
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "household_id": HOUSEHOLD,
        "entity_id": entity_id,
        "attribute": attribute,
        **columns,
        "valid_from": date.fromisoformat(valid_from),
        "valid_to": None,
        "replaces": None,
        "replaced_by": None,
        "status": "active",
        "recorded_at": at("2026-03-01"),
        "retracted_at": None,
        "retraction_reason": None,
        "source_kind": "seed",
        "source_ref": "test",
        "proposal_id": None,
        "life_event_id": None,
    }
    values.update(fields)
    return FactRow(**values)


def replaced(
    old: FactRow, new_value: int, valid_from: str, recorded: str
) -> tuple[FactRow, FactRow]:
    """`old` replaced by a new value from `valid_from`, recorded on `recorded`: (old, new)."""
    new = fact(
        old.entity_id,
        old.attribute,
        new_value,
        valid_from,
        replaces=old.id,
        recorded_at=at(recorded),
        source_kind="session",
        proposal_id=uuid.uuid4(),
    )
    closed = replace(old, valid_to=new.valid_from, replaced_by=new.id, status="replaced")
    return closed, new
