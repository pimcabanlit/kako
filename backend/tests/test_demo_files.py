"""The demo household's files (`data/demo-household/`): read, checked, and each mistake named.

Phase 2, task 5: the demo household's seed and its later changes, as files the loader replays.
"""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from kako.demo.files import DEMO_DIR, DemoDataError, parse_money, parse_value, read_demo
from kako.demo.load import seed_time


def test_the_demo_files_fit_the_data_model() -> None:
    demo = read_demo()
    assert demo.household.name == "Villanueva household"
    assert demo.household.currency == "PHP"
    assert demo.household.as_of_date == date(2026, 8, 1)
    assert {p.key for p in demo.people} == {"mara", "jun", "lia"}
    assert len(demo.entities) == 11
    assert len(demo.facts) == 25
    assert [c.seq for c in demo.changes] == list(range(1, 19))
    kinds = {c.kind for c in demo.changes}
    assert kinds == {"new_fact", "replace_fact", "preference_pattern", "life_event"}
    # Every change after the seed is something an adult decided.
    assert {c.decided_by for c in demo.changes} <= {"mara", "jun"}
    assert {d.parent.name for d in demo.documents} == {"statements", "kb"}
    assert seed_time(demo) == datetime(2026, 8, 1, tzinfo=UTC)


def test_values_are_read_as_their_attribute_types() -> None:
    demo = read_demo()
    salary = next(f for f in demo.facts if f.attribute == "income.monthly_net")
    assert salary.value == 5_200_000  # ₱52,000.00 in centavos
    car = next(c for c in demo.changes if c.seq == 8)
    assert car.value == 40_143_063  # ₱401,430.63
    target_date = next(c for c in demo.changes if c.attribute == "goal.target_date")
    assert target_date.value == date(2031, 12, 1)
    rate = next(f for f in demo.facts if f.attribute == "debt.monthly_rate")
    assert rate.value == Decimal("0.03")
    event = next(c for c in demo.changes if c.kind == "life_event")
    assert event.life_event == "new_job"
    assert isinstance(event.value, str)  # a life event's description, not a fact value


def test_every_document_a_change_cites_is_in_the_folder() -> None:
    demo = read_demo()
    names = {str(d.relative_to(DEMO_DIR)) for d in demo.documents}
    statements = {c.source_ref for c in demo.changes if c.source_kind == "statement"}
    assert statements
    assert statements <= names


@pytest.mark.parametrize(
    ("text", "centavos"),
    [("85000.00", 8_500_000), ("0.00", 0), ("401430.63", 40_143_063), ("7", 700), ("0.5", 50)],
)
def test_parse_money(text: str, centavos: int) -> None:
    assert parse_money(text) == centavos


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("12.345", "more than two decimals"),
        ("pesos", "isn't an amount"),
        ("NaN", "more than two decimals"),
        ("Infinity", "more than two decimals"),
    ],
)
def test_parse_money_refuses(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_money(text)


def test_parse_value_checks_the_attribute() -> None:
    with pytest.raises(ValueError, match="isn't a rate"):
        parse_value("debt.monthly_rate", "three percent")
    with pytest.raises(KeyError):
        parse_value("no.such_attribute", "1")


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """A copy of the demo files to break, one mistake per test."""
    copy = tmp_path / "demo"
    shutil.copytree(DEMO_DIR, copy)
    return copy


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_a_bad_value_names_its_file_and_line(folder: Path) -> None:
    _edit(folder / "facts.csv", "52000.00", "52000.005")
    with pytest.raises(DemoDataError, match=r"^facts\.csv:2: .*more than two decimals"):
        read_demo(folder)


def test_a_change_without_its_time_zone_is_refused(folder: Path) -> None:
    _edit(folder / "changes.csv", "2026-09-15T10:00:00+08:00", "2026-09-15T10:00:00")
    with pytest.raises(DemoDataError, match=r"^changes\.csv:2: recorded_at needs its time zone"):
        read_demo(folder)


def test_a_change_can_not_come_from_the_seed(folder: Path) -> None:
    _edit(folder / "changes.csv", ",session,session-2:plan-v2,", ",seed,session-2:plan-v2,")
    with pytest.raises(DemoDataError, match=r"^changes\.csv:2: 'seed' isn't a source"):
        read_demo(folder)


def test_an_unknown_change_kind_is_refused(folder: Path) -> None:
    _edit(folder / "changes.csv", ",new_fact,card,", ",overwrite,card,")
    with pytest.raises(DemoDataError, match=r"^changes\.csv:2: 'overwrite' isn't a change kind"):
        read_demo(folder)


def test_changes_must_be_in_order(folder: Path) -> None:
    _edit(folder / "changes.csv", "3,2026-10-16T09:00:00+08:00", "3,2026-09-01T09:00:00+08:00")
    with pytest.raises(DemoDataError, match="change 3 is out of order"):
        read_demo(folder)


def test_a_change_names_a_known_entity_and_person(folder: Path) -> None:
    _edit(folder / "changes.csv", ",new_fact,card,", ",new_fact,boat,")
    with pytest.raises(DemoDataError, match="change 1 has unknown entity"):
        read_demo(folder)


def test_a_change_is_decided_by_a_known_person(folder: Path) -> None:
    _edit(folder / "changes.csv", "plan-v2,,mara,", "plan-v2,,lola,")
    with pytest.raises(DemoDataError, match="change 1 decided by unknown person"):
        read_demo(folder)


def test_a_fact_can_not_name_a_later_life_event(folder: Path) -> None:
    _edit(folder / "changes.csv", "session-2:plan-v2,,mara", "session-2:plan-v2,new_job,mara")
    with pytest.raises(DemoDataError, match="change 1 names a later life event"):
        read_demo(folder)


def test_the_columns_are_checked(folder: Path) -> None:
    _edit(folder / "people.csv", "key,display_name,role,birth_year", "key,name,role,birth_year")
    with pytest.raises(DemoDataError, match=r"people\.csv: the columns must be"):
        read_demo(folder)
