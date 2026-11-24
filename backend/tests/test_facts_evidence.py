"""V-09: every number a proposal would write appears in its quoted evidence (`facts.evidence`)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from kako.facts.evidence import unquoted
from kako.facts.proposals import fact_payload, life_event_payload, retract_payload

SALARY = uuid.UUID("00000000-0000-4000-8000-000000000001")
OLD = uuid.UUID("00000000-0000-4000-8000-000000000002")
TODAY = date(2026, 11, 20)
JOB = "Mara here. I got the new job! I start on Dec 1 and take home ₱68,000 a month."


def _salary(centavos: int, valid_from: date = date(2026, 12, 1)) -> dict[str, Any]:
    return fact_payload(
        entity_id=SALARY,
        attribute_key="income.monthly_net",
        value=centavos,
        valid_from=valid_from,
        replaces=OLD,
    )


def test_the_new_job_is_quoted() -> None:
    assert unquoted("replace_fact", _salary(6_800_000), [JOB], today=TODAY) == []


def test_a_number_not_in_the_quote_is_found() -> None:
    missing = unquoted("replace_fact", _salary(6_850_000), [JOB], today=TODAY)
    assert missing == ["the value ₱68,500.00"]


def test_a_start_date_not_said_is_found() -> None:
    missing = unquoted("replace_fact", _salary(6_800_000, date(2027, 1, 1)), [JOB], today=TODAY)
    assert missing == ["valid_from 2027-01-01"]


def test_a_start_date_may_be_the_day_it_was_said() -> None:
    quote = "The card is at ₱76,880 now."
    payload = fact_payload(
        entity_id=SALARY, attribute_key="debt.balance", value=7_688_000, valid_from=TODAY
    )
    assert unquoted("new_fact", payload, [quote], today=TODAY) == []
    assert unquoted("new_fact", payload, [quote], today=date(2026, 11, 21)) == [
        "valid_from 2026-11-20"
    ]


@pytest.mark.parametrize(
    "quote",
    [
        "68000 a month from December 1",
        "68,000 pesos, starting 1 December",
        "PHP 68,000.00 from 2026-12-01",
        "about 68k a month, from Dec 1st",
        "68 thousand from 1/12/2026",
        "₱68,000 from December 2026",
    ],
)
def test_the_household_writes_numbers_many_ways(quote: str) -> None:
    assert unquoted("replace_fact", _salary(6_800_000), [quote], today=TODAY) == []


def test_a_day_with_no_year_counts_only_near_the_household_date() -> None:
    far = _salary(6_800_000, date(2028, 12, 1))
    assert unquoted("replace_fact", far, ["₱68,000 from Dec 1"], today=TODAY) == [
        "valid_from 2028-12-01"
    ]


def test_numbers_from_several_quotes_count() -> None:
    quotes = ["I start on Dec 1.", "The pay is ₱68,000."]
    assert unquoted("replace_fact", _salary(6_800_000), quotes, today=TODAY) == []


def test_a_rate_as_a_percentage_or_a_fraction() -> None:
    payload = fact_payload(
        entity_id=SALARY,
        attribute_key="debt.monthly_rate",
        value=Decimal("0.035"),
        valid_from=TODAY,
    )
    assert unquoted("new_fact", payload, ["The card now charges 3.5% a month"], today=TODAY) == []
    assert unquoted("new_fact", payload, ["The card charges 0.035"], today=TODAY) == []
    assert unquoted("new_fact", payload, ["The card charges 3% a month"], today=TODAY) == [
        "the value 3.5%"
    ]


def test_a_whole_number_and_a_target_in_years() -> None:
    payload = fact_payload(
        entity_id=None,
        attribute_key="household.emergency_months_target",
        value=6,
        valid_from=TODAY,
    )
    assert unquoted("new_fact", payload, ["We want 6 months of cash"], today=TODAY) == []
    assert unquoted("new_fact", payload, ["We want half a year"], today=TODAY) == ["the value 6"]


def test_numbers_in_free_text_must_be_quoted() -> None:
    payload = fact_payload(
        entity_id=None,
        attribute_key="constraint.note",
        value="₱5,000 a month goes to Jun's parents",
        valid_from=TODAY,
    )
    said = "Remember ₱5,000 a month goes to Jun's parents."
    assert unquoted("new_fact", payload, [said], today=TODAY) == []
    assert unquoted("new_fact", payload, ["Some goes to Jun's parents"], today=TODAY) == [
        "a number in the value 5000"
    ]


def test_a_text_value_with_no_number_needs_none() -> None:
    payload = fact_payload(
        entity_id=None,
        attribute_key="preference.debt_vs_flexibility",
        value="flexibility",
        valid_from=TODAY,
    )
    assert unquoted("preference_pattern", payload, ["We keep cash on hand"], today=TODAY) == []


def test_a_life_event() -> None:
    payload = life_event_payload(
        event_id=uuid.uuid4(),
        kind="new_job",
        description="Mara starts a new job on Dec 1 at ₱68,000 take-home",
        occurs_on=date(2026, 12, 1),
        source_ref="conv:s4:t1",
    )
    assert unquoted("life_event", payload, [JOB], today=TODAY) == []
    assert unquoted("life_event", payload, ["I got a new job"], today=TODAY) == [
        "occurs_on 2026-12-01",
        "a number in the description Dec 1",
        "a number in the description 68000",
    ]
    # A date in the description is found in the quote, written another way.
    said = "New job from 2026-12-01, ₱68,000 take-home"
    assert unquoted("life_event", payload, [said], today=TODAY) == []


def test_a_retraction_reason() -> None:
    payload = retract_payload(OLD, "The balance was ₱86,000, not ₱85,000")
    said = "Sorry, the card was ₱86,000 and not ₱85,000."
    assert unquoted("retract_fact", payload, [said], today=TODAY) == []
    assert unquoted("retract_fact", payload, ["That was wrong"], today=TODAY) == [
        "a number in the reason 86000",
        "a number in the reason 85000",
    ]


def test_a_number_run_into_letters_is_never_a_match() -> None:
    assert unquoted("replace_fact", _salary(6_800_000), ["W68000 Dec 1"], today=TODAY) == [
        "the value ₱68,000.00"
    ]
