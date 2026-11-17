"""What an approved proposal lets the fact store write, and whether a write is exactly that.

docs/data-model.md, "Proposal payloads": a proposal that writes a fact carries the write in its
`payload`, and the store writes only what the household approved (V-08; REVIEW.md rule 4, "an
approval applied to a different proposal or value from the one approved"). Each proposal writes one
fact at most.

Payloads are JSON. Money and whole numbers are JSON integers (money in centavos), a rate is a
decimal string such as "0.035" (never a float), a date is "YYYY-MM-DD", and ids are UUID strings.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from kako.facts.attributes import Attribute, attribute
from kako.facts.model import FactValue
from kako.facts.values import FactValueError, check_value

# Which approved proposals can create, replace or retract a fact.
RECORD_KINDS: Final = frozenset({"new_fact", "preference_pattern"})
REPLACE_KINDS: Final = frozenset({"replace_fact", "preference_pattern"})
RETRACT_KINDS: Final = frozenset({"retract_fact"})

_RATE_PLACES = Decimal("0.000001")


class PayloadError(ValueError):
    """A proposal whose payload isn't the write being made."""


def encode_value(attr: Attribute, value: FactValue) -> int | str:
    """A checked value as it is written in a payload."""
    check_value(attr, value)  # so the type below is the attribute's
    if isinstance(value, Decimal):
        return format(value.quantize(_RATE_PLACES), "f")
    if isinstance(value, date):
        return value.isoformat()
    return value


def decode_value(attr: Attribute, raw: Any) -> FactValue:
    """A payload's value as the attribute's type. Raises FactValueError if it isn't one."""
    value: Any = raw
    if attr.value_type == "rate":
        if not isinstance(raw, str):
            raise FactValueError(f'{attr.key} is written as a decimal string, such as "0.035"')
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise FactValueError(f"{attr.key}: {raw!r} isn't a number") from exc
    elif attr.value_type == "date":
        if not isinstance(raw, str):
            raise FactValueError(f'{attr.key} is written as a date, such as "2026-12-01"')
        try:
            value = date.fromisoformat(raw)
        except ValueError as exc:
            raise FactValueError(f"{attr.key}: {raw!r} isn't a date") from exc
    check_value(attr, value)
    return value  # type: ignore[no-any-return]


def _id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def fact_payload(
    *,
    entity_id: uuid.UUID | None,
    attribute_key: str,
    value: FactValue,
    valid_from: date,
    valid_to: date | None = None,
    replaces: uuid.UUID | None = None,
    life_event_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The payload of a proposal that records a fact, or replaces `replaces` with it."""
    payload: dict[str, Any] = {
        "entity_id": _id(entity_id),
        "attribute": attribute_key,
        "value": encode_value(attribute(attribute_key), value),
        "valid_from": valid_from.isoformat(),
        "valid_to": None if valid_to is None else valid_to.isoformat(),
        "life_event_id": _id(life_event_id),
    }
    if replaces is not None:
        payload["replaces"] = str(replaces)
    return payload


def retract_payload(fact_id: uuid.UUID, reason: str) -> dict[str, Any]:
    """The payload of a proposal that retracts a fact."""
    return {"fact_id": str(fact_id), "reason": reason}


def _canonical(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The payload with its value written the one way `encode_value` writes it."""
    canonical = dict(payload)
    try:
        attr = attribute(str(payload.get("attribute")))
    except KeyError:
        return canonical
    if "value" in payload:
        try:
            canonical["value"] = encode_value(attr, decode_value(attr, payload["value"]))
        except FactValueError as exc:
            raise PayloadError(f"its value doesn't fit: {exc}") from exc
    return canonical


def check_payload(payload: Any, expected: Mapping[str, Any]) -> None:
    """Raise PayloadError unless `payload` says exactly what `expected` (the write) says."""
    if not isinstance(payload, Mapping):
        raise PayloadError("it has no write in its payload")
    approved = _canonical(payload)
    if set(approved) != set(expected):
        missing = sorted(set(expected) - set(approved))
        extra = sorted(set(approved) - set(expected))
        parts = ([f"missing {', '.join(missing)}"] if missing else []) + (
            [f"unexpected {', '.join(extra)}"] if extra else []
        )
        raise PayloadError(f"its payload is a different kind of write ({'; '.join(parts)})")
    differ = sorted(key for key in expected if approved[key] != expected[key])
    if differ:
        raise PayloadError(f"it approved a different {', '.join(differ)}")
