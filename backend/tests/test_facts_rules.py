"""The validation rules V-01 to V-08 and V-16 over fact rows, and the value checks."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from kako.facts.attributes import CATALOG, VALUE_COLUMN, attribute
from kako.facts.rules import ApprovedRow, validate, windows_overlap
from kako.facts.values import FactValueError, check_value
from tests.support.data_model import DATA_MODEL
from tests.support.facts import at, entity, fact, replaced

SALARY = entity()
CARD = entity("debt", "Credit card")
FUND = entity("account", "Emergency fund")
SAVINGS = entity("account", "Savings")
ENTITIES = [SALARY, CARD, FUND, SAVINGS]


def _rules(facts, approved=frozenset(), rows=()):  # type: ignore[no-untyped-def]
    return sorted({v.rule for v in validate(facts, ENTITIES, set(approved), rows)})


def test_a_clean_history_passes() -> None:
    old = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01")
    closed, new = replaced(old, 6_800_000, "2026-12-01", "2026-11-20")
    assert validate([closed, new], ENTITIES, {new.proposal_id}) == []  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("row", "rule"),
    [
        (fact(SALARY.id, "income.salary", 1, "2026-03-01"), "V-01"),  # not in the catalog
        (fact(SALARY.id, "income.monthly_net", "52000", "2026-03-01"), "V-01"),  # text, not money
        (fact(CARD.id, "income.monthly_net", 100, "2026-03-01"), "V-01"),  # wrong entity kind
        (fact(None, "income.monthly_net", 100, "2026-03-01"), "V-01"),  # needs an entity
        (fact(SALARY.id, "preference.debt_strategy", "avalanche", "2026-03-01"), "V-01"),
        (fact(None, "preference.debt_strategy", "fastest", "2026-03-01"), "V-01"),  # not a choice
        (fact(SALARY.id, "income.monthly_net", -1, "2026-03-01"), "V-07"),
        (fact(CARD.id, "debt.monthly_rate", Decimal("1.5"), "2026-03-01"), "V-07"),
    ],
)
def test_value_rules(row, rule: str) -> None:  # type: ignore[no-untyped-def]
    assert _rules([row]) == [rule]


def test_v02_overlapping_windows() -> None:
    a = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01")
    b = fact(SALARY.id, "income.monthly_net", 5_300_000, "2026-06-01")
    assert _rules([a, b]) == ["V-02"]
    # Back to back is fine: half-open windows.
    a_closed = replace(a, valid_to=date(2026, 6, 1))
    assert _rules([a_closed, b]) == []


def test_v03_a_gap_in_the_chain() -> None:
    old = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01")
    closed, new = replaced(old, 6_800_000, "2026-12-01", "2026-11-20")
    gap = replace(closed, valid_to=date(2026, 11, 1))
    assert "V-03" in _rules([gap, new], {new.proposal_id})


def test_v04_one_way_links() -> None:
    old = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01")
    closed, new = replaced(old, 6_800_000, "2026-12-01", "2026-11-20")
    assert "V-04" in _rules([closed, replace(new, replaces=None)], {new.proposal_id})
    assert "V-04" in _rules([replace(closed, replaced_by=None), new], {new.proposal_id})
    assert "V-04" in _rules([replace(closed, status="active"), new], {new.proposal_id})


def test_v05_a_retraction_needs_its_reason() -> None:
    row = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01")
    assert _rules([replace(row, status="retracted", retracted_at=at("2026-04-01"))]) == ["V-05"]
    good = replace(row, status="retracted", retracted_at=at("2026-04-01"), retraction_reason="typo")
    assert _rules([good]) == []
    assert _rules([replace(row, retraction_reason="typo")]) == ["V-05"]


def test_v06_inside_the_entity_life() -> None:
    late = entity("debt", "Car loan", opened_on=date(2026, 5, 1), closed_on=date(2027, 5, 1))
    rows = [
        fact(late.id, "debt.balance", 100, "2026-04-01"),
        fact(late.id, "debt.minimum_payment", 100, "2027-05-01"),
    ]
    found = validate(rows, [late], set())
    assert [v.rule for v in found] == ["V-06", "V-06"]


def test_v08_only_the_seed_skips_a_proposal() -> None:
    row = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01", source_kind="session")
    assert _rules([row]) == ["V-08"]
    proposal = uuid.uuid4()
    assert _rules([replace(row, proposal_id=proposal)], {proposal}) == []
    event = ApprovedRow("life_event", uuid.uuid4(), uuid.uuid4())
    assert _rules([], rows=[event]) == ["V-08"]


def test_v08_a_seed_has_no_proposal_and_a_proposal_writes_once() -> None:
    proposal = uuid.uuid4()
    seed = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01")
    assert _rules([replace(seed, proposal_id=proposal)], {proposal}) == ["V-08"]
    # A seed fact that replaces one: V-08, and V-04 because nothing names it back.
    assert _rules([replace(seed, replaces=uuid.uuid4())]) == ["V-04", "V-08"]
    first = fact(None, "household.emergency_months_target", 3, "2026-03-01",
                 source_kind="session", proposal_id=proposal)  # fmt: skip
    second = fact(SALARY.id, "income.monthly_net", 5_200_000, "2026-03-01",
                  source_kind="session", proposal_id=proposal)  # fmt: skip
    assert _rules([first, second], {proposal}) == ["V-08"]


def test_v16_one_emergency_fund_at_a_time() -> None:
    one = fact(FUND.id, "account.purpose", "emergency", "2026-03-01")
    two = fact(SAVINGS.id, "account.purpose", "emergency", "2026-06-01")
    assert _rules([one, two]) == ["V-16"]
    assert _rules([replace(one, valid_to=date(2026, 6, 1)), two]) == []
    general = fact(SAVINGS.id, "account.purpose", "general", "2026-06-01")
    assert _rules([one, general]) == []


def test_windows_overlap_is_half_open() -> None:
    d = date.fromisoformat
    assert windows_overlap(d("2026-01-01"), None, d("2026-05-01"), None)
    assert not windows_overlap(d("2026-01-01"), d("2026-05-01"), d("2026-05-01"), None)
    assert windows_overlap(d("2026-01-01"), d("2026-05-02"), d("2026-05-01"), None)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("income.monthly_net", True),
        ("income.monthly_net", 1.5),
        ("debt.monthly_rate", 0.03),
        ("debt.monthly_rate", Decimal("0.0300001")),
        ("income.pay_day", 32),
        ("goal.target_date", "2027-01-01"),
        ("expense.essential", "maybe"),
        ("preference.note", "  "),
    ],
)
def test_values_that_dont_fit(key: str, value: object) -> None:
    with pytest.raises(FactValueError):
        check_value(attribute(key), value)


def test_the_catalog_matches_the_doc() -> None:
    """Every attribute in code is in data-model.md's catalog, with the same type, and back."""
    text = DATA_MODEL.read_text(encoding="utf-8")
    section = text.split("### Attribute catalog", 1)[1].split("### `life_event`", 1)[0]
    rows = [
        [c.strip().strip("`") for c in line.strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("| `")
    ]
    documented = {row[0]: row for row in rows}
    assert sorted(documented) == sorted(CATALOG)
    for key, attr in CATALOG.items():
        assert documented[key][2] == attr.value_type, key
        kinds = documented[key][1]
        if attr.household_wide:
            assert kinds == "(household)", key
        else:
            assert {k.strip() for k in kinds.split(",")} == set(attr.entity_kinds), key
    assert set(VALUE_COLUMN) == {"money", "rate", "int", "date", "text"}
