"""Snapshots `on` a date and `known_at` a time (docs/data-model.md, "Reading facts")."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from kako.facts.snapshot import snapshot_hash, take_snapshot
from tests.support.facts import HOUSEHOLD, at, entity, fact, replaced

SALARY = entity()
P = "income.monthly_net"


def _salary_history() -> tuple:  # type: ignore[type-arg]
    """₱52,000 from Mar 1; told on Nov 20 that it is ₱68,000 from Dec 1."""
    old = fact(SALARY.id, P, 5_200_000, "2026-03-01", recorded_at=at("2026-03-01"))
    return replaced(old, 6_800_000, "2026-12-01", recorded="2026-11-20")


def _values(snap) -> list:  # type: ignore[no-untyped-def,type-arg]
    return [f.value for f in snap.facts]


def test_what_was_true_on_each_day() -> None:
    old, new = _salary_history()
    facts = [old, new]
    assert _values(take_snapshot(HOUSEHOLD, facts, date(2026, 2, 28))) == []
    assert _values(take_snapshot(HOUSEHOLD, facts, date(2026, 3, 1))) == [5_200_000]
    assert _values(take_snapshot(HOUSEHOLD, facts, date(2026, 11, 30))) == [5_200_000]
    # Half-open: Dec 1 belongs to the new value only.
    assert _values(take_snapshot(HOUSEHOLD, facts, date(2026, 12, 1))) == [6_800_000]


def test_known_at_sees_the_old_value_still_open() -> None:
    """On Sep 15, Kako believed ₱52,000 would still hold on Dec 1: the job wasn't known yet."""
    old, new = _salary_history()
    facts = [old, new]
    then = take_snapshot(HOUSEHOLD, facts, date(2026, 12, 1), known_at=at("2026-09-15"))
    assert _values(then) == [5_200_000]
    after = take_snapshot(HOUSEHOLD, facts, date(2026, 12, 1), known_at=at("2026-11-20", 10))
    assert _values(after) == [6_800_000]


def test_a_retracted_fact_is_gone_from_its_retraction_on() -> None:
    """V-05: before the retraction Kako believed it; from then on no snapshot includes it."""
    old, new = _salary_history()
    wrong = replace(
        new, status="retracted", retracted_at=at("2026-11-25"), retraction_reason="typo"
    )
    restored = replace(old, valid_to=None, replaced_by=None, status="active")
    facts = [restored, wrong]
    before = take_snapshot(HOUSEHOLD, facts, date(2026, 12, 1), known_at=at("2026-11-24"))
    assert _values(before) == [6_800_000]
    after = take_snapshot(HOUSEHOLD, facts, date(2026, 12, 1), known_at=at("2026-11-25"))
    assert _values(after) == [5_200_000]
    assert _values(take_snapshot(HOUSEHOLD, facts, date(2026, 12, 1))) == [5_200_000]


def test_a_fact_recorded_later_is_unknown_before() -> None:
    old, _ = _salary_history()
    assert (
        _values(take_snapshot(HOUSEHOLD, [old], date(2026, 6, 1), known_at=at("2026-02-01"))) == []
    )


def test_a_closed_window_without_successor_keeps_its_end() -> None:
    gym = entity("expense", "Gym")
    row = fact(gym.id, "expense.monthly_amount", 150_000, "2026-03-01", valid_to=date(2026, 6, 1))
    assert _values(take_snapshot(HOUSEHOLD, [row], date(2026, 5, 31))) == [150_000]
    assert _values(take_snapshot(HOUSEHOLD, [row], date(2026, 6, 1))) == []


def test_other_households_are_left_out() -> None:
    import uuid

    other = fact(
        None, "household.emergency_months_target", 3, "2026-03-01", household_id=uuid.uuid4()
    )
    assert take_snapshot(HOUSEHOLD, [other], date(2026, 6, 1)).facts == ()


def test_the_hash_is_the_sorted_ids_and_stable() -> None:
    old, new = _salary_history()
    one = take_snapshot(HOUSEHOLD, [old, new], date(2026, 12, 1))
    two = take_snapshot(HOUSEHOLD, [new, old], date(2026, 12, 1))
    assert one.hash == two.hash == snapshot_hash([new.id])
    assert one.hash != take_snapshot(HOUSEHOLD, [old, new], date(2026, 11, 1)).hash
    assert one.get(SALARY.id, P) == new
    assert one.get(SALARY.id, "income.pay_day") is None
