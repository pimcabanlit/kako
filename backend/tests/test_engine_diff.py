"""F-DIFF-1: the worked example's diff, plan v2 to plan v3, comes out as written
(docs/data-model.md, "Worked example: a new job"), and each label in its own case.

Phase 2, task 4, done when: the worked example's diff (plan v2 to v3) comes out as written.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date

import pytest

from kako.engine import compute
from kako.engine.diff import Diff, FactChange, diff
from kako.facts.model import FactRow
from kako.facts.snapshot import take_snapshot
from tests.support.facts import HOUSEHOLD, at
from tests.support.villanueva import DEC_1, SEP_15, Villanueva, build


def _fact(h: Villanueva, key: str | None, attribute: str, value: object) -> FactRow:
    entity_id = None if key is None else h.ids[key]
    return next(
        f for f in h.facts
        if f.entity_id == entity_id and f.attribute == attribute and f.value == value
    )  # fmt: skip


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


@pytest.fixture(scope="module")
def v2_to_v3(house: Villanueva) -> Diff:
    """Plan v2 as it was made (Sep 15, as Kako knew it then) against plan v3 (Dec 1)."""
    v2 = compute(
        take_snapshot(HOUSEHOLD, house.facts, SEP_15, at("2026-09-15", 18)), house.entities
    )
    v3 = compute(take_snapshot(HOUSEHOLD, house.facts, DEC_1, at("2026-12-01", 18)), house.entities)
    split = uuid.UUID("00000000-0000-4000-8000-0000000000d1")  # "split the surplus", Sep 15
    assumptions = {split: [_fact(house, "mara_salary", "income.monthly_net", 5_200_000).id]}
    return diff(v2, v3, house.facts, assumptions)


def _labels(changes: tuple[FactChange, ...]) -> set[tuple[str, str, object, object]]:
    return {
        (c.label, c.attribute, c.old.value if c.old else None, c.new.value if c.new else None)
        for c in changes
    }


def test_income_rose_because_a_fact_was_replaced(v2_to_v3: Diff, house: Villanueva) -> None:
    income = v2_to_v3.get("cashflow.monthly_income")
    assert income is not None
    assert income.old is not None
    assert income.new is not None
    assert income.new.value - income.old.value == 1_600_000  # type: ignore[operator]  # +₱16,000
    assert _labels(income.facts) == {("replaced", "income.monthly_net", 5_200_000, 6_800_000)}


def test_surplus_and_the_card(v2_to_v3: Diff, house: Villanueva) -> None:
    surplus = v2_to_v3.get("cashflow.monthly_surplus")
    assert surplus is not None
    assert (surplus.old.value, surplus.new.value) == (905_000, 2_505_000)  # type: ignore[union-attr]
    assert ("replaced", "income.monthly_net", 5_200_000, 6_800_000) in _labels(surplus.facts)
    card = v2_to_v3.get("debt.payoff_months", house.ids["card"])
    assert card is not None
    assert (card.old.value, card.new.value) == (17, 7)  # type: ignore[union-attr]
    # Card extra ₱4,000 → ₱10,000: the household chose differently. The balance is a statement.
    assert ("allocation", "plan.allocation", 400_000, 1_000_000) in _labels(card.facts)
    assert ("replaced", "debt.balance", 8_500_000, 7_688_000) in _labels(card.facts)


def test_emergency_target_in_5_months_not_12(v2_to_v3: Diff) -> None:
    months = v2_to_v3.get("savings.months_to_target")
    assert months is not None
    assert (months.old.value, months.new.value) == (12, 5)  # type: ignore[union-attr]
    assert _labels(months.facts) >= {
        ("allocation", "plan.allocation", 505_000, 1_000_000),
        ("replaced", "account.balance", 15_000_000, 16_010_000),
    }


def test_a_new_house_fund(v2_to_v3: Diff, house: Villanueva) -> None:
    goal = v2_to_v3.get("goal.months_to_target", house.ids["house"])
    assert goal is not None
    assert goal.old is None
    assert goal.new is not None
    assert ("allocation", "plan.allocation", None, 505_000) in _labels(goal.facts)
    assert ("new", "goal.target_amount", None, 30_000_000) in _labels(goal.facts)


def test_what_did_not_change_is_not_listed(v2_to_v3: Diff) -> None:
    assert v2_to_v3.get("plan.unallocated") is None  # ₱0 both times
    assert v2_to_v3.get("cashflow.monthly_expenses") is None
    # 13th-month pay appears in December, but its fact was true and known in September.
    thirteenth = v2_to_v3.get("cashflow.thirteenth_month")
    assert thirteenth is not None
    assert thirteenth.old is None
    assert thirteenth.facts == ()


def test_the_split_decision_is_to_revisit(v2_to_v3: Diff) -> None:
    (revisit,) = v2_to_v3.decisions
    assert _labels(revisit.facts) == {("replaced", "income.monthly_net", 5_200_000, 6_800_000)}


def test_the_fact_changes_once_each(v2_to_v3: Diff) -> None:
    every = _labels(v2_to_v3.fact_changes)
    assert every >= {
        ("replaced", "income.monthly_net", 5_200_000, 6_800_000),
        ("replaced", "debt.balance", 8_500_000, 7_688_000),
        ("replaced", "account.balance", 15_000_000, 16_010_000),
        ("allocation", "plan.allocation", 400_000, 1_000_000),
        ("allocation", "plan.allocation", 505_000, 1_000_000),
        ("allocation", "plan.allocation", None, 505_000),
    }
    assert len(v2_to_v3.fact_changes) == len(every)


def test_a_retraction_is_labelled_a_fixed_mistake(house: Villanueva) -> None:
    """Mara's ₱68,000 was a typo, retracted on Nov 21: on Dec 1 the old ₱52,000 is back."""
    facts = list(house.facts)
    old = _fact(house, "mara_salary", "income.monthly_net", 5_200_000)
    typo = _fact(house, "mara_salary", "income.monthly_net", 6_800_000)
    facts[facts.index(typo)] = replace(
        typo, status="retracted", retracted_at=at("2026-11-21"), retraction_reason="typo"
    )
    facts[facts.index(old)] = replace(old, status="active", valid_to=None, replaced_by=None)
    before = compute(take_snapshot(HOUSEHOLD, house.facts, DEC_1, at("2026-11-20", 18)),
                     house.entities)  # fmt: skip
    after = compute(take_snapshot(HOUSEHOLD, facts, DEC_1, at("2026-11-21", 18)), house.entities)
    income = diff(before, after, facts).get("cashflow.monthly_income")
    assert income is not None
    assert _labels(income.facts) == {("retracted", "income.monthly_net", 6_800_000, 5_200_000)}
    split = uuid.uuid4()
    revisit = diff(before, after, facts, {split: [typo.id]}).decisions
    assert _labels(revisit[0].facts) == {("retracted", "income.monthly_net", 6_800_000, 5_200_000)}


def test_a_fact_that_ended(house: Villanueva) -> None:
    facts = list(house.facts)
    jun13 = _fact(house, "jun_salary", "income.thirteenth_month", 4_800_000)
    facts[facts.index(jun13)] = replace(jun13, valid_to=date(2026, 12, 15))
    dec, jan = date(2026, 12, 1), date(2026, 12, 31)
    a = compute(take_snapshot(HOUSEHOLD, facts, dec), house.entities)
    b = compute(take_snapshot(HOUSEHOLD, facts, jan), house.entities)
    thirteenth = diff(a, b, facts).get("cashflow.thirteenth_month")
    assert thirteenth is not None
    assert _labels(thirteenth.facts) == {("ended", "income.thirteenth_month", 4_800_000, None)}


def test_a_diff_reads_only_its_own_household(house: Villanueva) -> None:
    """Another household's facts can't explain this one's figures, even by mistake."""
    run = compute(take_snapshot(HOUSEHOLD, house.facts, DEC_1), house.entities)
    stranger = replace(house.facts[0], id=uuid.uuid4(), household_id=uuid.uuid4())
    with pytest.raises(ValueError, match="its own household"):
        diff(run, run, [*house.facts, stranger])
    other = replace(run, household_id=uuid.uuid4())
    with pytest.raises(ValueError, match="same household"):
        diff(run, other, house.facts)
