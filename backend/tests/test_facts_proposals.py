"""A proposal's payload is the write it approves (V-08; REVIEW.md rule 4), written one way."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from kako.facts.attributes import attribute
from kako.facts.proposals import (
    PayloadError,
    check_payload,
    decode_value,
    encode_value,
    fact_payload,
    retract_payload,
)
from kako.facts.values import FactValueError

CARD = uuid.UUID("00000000-0000-4000-8000-000000000002")
OLD = uuid.UUID("00000000-0000-4000-8000-000000000003")


@pytest.mark.parametrize(
    ("key", "value", "written"),
    [
        ("debt.balance", 7_688_000, 7_688_000),
        ("debt.monthly_rate", Decimal("0.035"), "0.035000"),
        ("goal.target_date", date(2027, 6, 1), "2027-06-01"),
        ("preference.debt_strategy", "avalanche", "avalanche"),
        ("household.emergency_months_target", 5, 5),
    ],
)
def test_values_round_trip(key: str, value: Any, written: Any) -> None:
    attr = attribute(key)
    assert encode_value(attr, value) == written
    assert decode_value(attr, written) == value


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("debt.monthly_rate", 0.035),  # a float is never a rate
        ("debt.monthly_rate", "three percent"),
        ("debt.balance", "7688000"),
        ("debt.balance", True),
        ("debt.balance", 76_880.5),
        ("goal.target_date", 20270601),
        ("goal.target_date", "June 2027"),
        ("preference.debt_strategy", "fastest"),
    ],
)
def test_values_that_dont_decode(key: str, raw: Any) -> None:
    with pytest.raises(FactValueError):
        decode_value(attribute(key), raw)


def _card_balance(**changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "entity_id": CARD,
        "attribute_key": "debt.balance",
        "value": 7_688_000,
        "valid_from": date(2026, 12, 1),
        "replaces": OLD,
    }
    fields.update(changes)
    return fact_payload(**fields)


def test_the_same_write_passes_however_the_rate_is_written() -> None:
    check_payload(_card_balance(), _card_balance())
    rate = {"attribute_key": "debt.monthly_rate", "value": Decimal("0.035")}
    approved = {**_card_balance(**rate), "value": "0.0350"}
    check_payload(approved, _card_balance(**rate))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_card_balance(value=1), "different value"),
        (_card_balance(valid_from=date(2026, 11, 1)), "different valid_from"),
        (_card_balance(replaces=uuid.uuid4()), "different replaces"),
        (_card_balance(replaces=None), "missing replaces"),
        ({**_card_balance(), "note": "x"}, "unexpected note"),
        (retract_payload(OLD, "typo"), "different kind of write"),
        ([], "no write"),
        (None, "no write"),
        ({**_card_balance(), "value": "7688000"}, "doesn't fit"),
    ],
)
def test_a_different_write_is_refused(payload: Any, message: str) -> None:
    with pytest.raises(PayloadError, match=message):
        check_payload(payload, _card_balance())


def test_a_retraction_names_its_fact_and_reason() -> None:
    check_payload(retract_payload(OLD, "typo"), retract_payload(OLD, "typo"))
    with pytest.raises(PayloadError, match="different fact_id"):
        check_payload(retract_payload(CARD, "typo"), retract_payload(OLD, "typo"))
