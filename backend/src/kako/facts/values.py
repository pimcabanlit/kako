"""A fact's value against its attribute: the type (V-01) and the range (V-07)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from kako.facts.attributes import VALUE_COLUMN, Attribute, attribute
from kako.facts.model import FactValue

_RATE_PLACES = Decimal("0.000001")  # NUMERIC(9,6)


class FactValueError(ValueError):
    """A value that doesn't fit its attribute."""


def check_value(attr: Attribute, value: Any) -> None:
    """Raise FactValueError unless `value` is the right type and in range for `attr`."""
    kind = attr.value_type
    where = f"{attr.key}"
    if kind in ("money", "int"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise FactValueError(f"{where} needs a whole number, not {type(value).__name__}")
        if kind == "money" and value < 0:
            raise FactValueError(f"{where} can't be negative (V-07)")
        if attr.minimum is not None and value < attr.minimum:
            raise FactValueError(f"{where} must be at least {attr.minimum}")
        if attr.maximum is not None and value > attr.maximum:
            raise FactValueError(f"{where} must be at most {attr.maximum}")
    elif kind == "rate":
        if not isinstance(value, Decimal) or not value.is_finite():
            raise FactValueError(f"{where} needs a Decimal fraction, such as Decimal('0.03')")
        if not Decimal(0) <= value <= Decimal(1):
            raise FactValueError(f"{where} is a fraction between 0 and 1 (V-07)")
        if value != value.quantize(_RATE_PLACES):
            raise FactValueError(f"{where} has more than six decimal places")
    elif kind == "date":
        if isinstance(value, datetime) or not isinstance(value, date):
            raise FactValueError(f"{where} needs a calendar date")
    else:  # text
        if not isinstance(value, str) or not value.strip():
            raise FactValueError(f"{where} needs some text")
        if attr.choices is not None and value not in attr.choices:
            allowed = ", ".join(sorted(attr.choices))
            raise FactValueError(f"{where} must be one of: {allowed}")


def value_columns(attr: Attribute, value: FactValue) -> dict[str, FactValue | None]:
    """The five `value_*` columns for a checked value: the attribute's one set, the rest null."""
    check_value(attr, value)
    columns: dict[str, FactValue | None] = dict.fromkeys(VALUE_COLUMN.values())
    columns[VALUE_COLUMN[attr.value_type]] = value
    return columns


def parse_money(text: str) -> int:
    """Pesos with at most two decimals, as exact centavos ("85000.00" is 8,500,000)."""
    try:
        pesos = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{text!r} isn't an amount in pesos") from exc
    centavos = pesos * 100
    if not pesos.is_finite() or centavos != centavos.to_integral_value():
        raise ValueError(f"{text!r} has more than two decimals")
    return int(centavos)


def parse_value(attribute_key: str, text: str) -> FactValue:
    """A value as its attribute's type, checked against the attribute (V-01, V-07)."""
    attr = attribute(attribute_key)
    value: FactValue
    if attr.value_type == "money":
        value = parse_money(text)
    elif attr.value_type == "rate":
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"{text!r} isn't a rate") from exc
    elif attr.value_type == "int":
        value = int(text)
    elif attr.value_type == "date":
        value = date.fromisoformat(text)
    else:
        value = text
    check_value(attr, value)
    return value
