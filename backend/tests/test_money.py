"""The money screen's numbers (docs/data-model.md, "The money screen"), on the worked example and on
seeded random households: the month's plan line by line, the split, each debt's month-by-month
schedule, what the household owns and owes, the milestones and the plan before its last change.
"""

from __future__ import annotations

import random
import uuid
from datetime import date
from decimal import Decimal

import pytest

from kako.engine import compute
from kako.engine.inputs import Inputs
from kako.engine.money import (
    NEVER_ROWS,
    debt_schedules,
    money_view,
    plan_before,
    plan_lines,
    split_of,
)
from kako.facts.snapshot import take_snapshot
from kako.planning.money import money_screen, percent
from tests.support.facts import HOUSEHOLD, entity, fact
from tests.support.villanueva import DEC_1, SEP_15, Villanueva, build
from tests.test_engine_properties import SEEDS, _household

NOV_20 = date(2026, 11, 20)


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _view(h: Villanueva, on: date):  # type: ignore[no-untyped-def]
    return money_view(take_snapshot(HOUSEHOLD, h.facts, on), h.entities)


def test_the_plan_on_dec_1_line_by_line_down_to_nothing_left(house: Villanueva) -> None:
    view = _view(house, DEC_1)
    assert [(line.kind, line.name, line.amount, line.left) for line in view.lines] == [
        ("in", "Jun's salary", 4_800_000, 4_800_000),
        ("in", "Mara's salary", 6_800_000, 11_600_000),
        ("need", "Rent and utilities", 4_000_000, 7_600_000),
        ("need", "Food", 2_000_000, 5_600_000),
        ("need", "School and transport", 1_000_000, 4_600_000),
        ("want", "Eating out", 600_000, 4_000_000),
        ("debt", "Credit card minimum", 255_000, 3_745_000),
        ("debt", "Car loan minimum", 1_240_000, 2_505_000),
        ("debt", "Credit card, extra", 1_000_000, 1_505_000),
        ("savings", "Emergency fund", 1_000_000, 505_000),
        ("savings", "House fund", 505_000, 0),
    ]
    # What is left after the surplus's lines is the engine's own figure.
    assert view.lines[7].left == view.run.value("cashflow.monthly_surplus")
    assert view.lines[-1].left == view.run.value("plan.unallocated")


def test_where_each_peso_goes(house: Villanueva) -> None:
    split = _view(house, DEC_1).split
    assert split is not None
    assert (split.needs, split.wants, split.debt, split.savings, split.unplanned, split.over) == (
        7_000_000, 600_000, 2_495_000, 1_505_000, 0, 0,
    )  # fmt: skip
    assert split.total == 11_600_000
    assert split.needs + split.wants + split.debt + split.savings + split.unplanned == split.total
    shares = [
        percent(p, split.total) for p in (split.needs, split.wants, split.debt, split.savings)
    ]
    assert shares == ["60%", "5%", "22%", "13%"]
    assert percent(1, 0) == "—"


def test_the_schedules_are_f_debt_2_month_by_month(house: Villanueva) -> None:
    view = _view(house, DEC_1)
    card, car = view.schedules
    assert (card.name, card.order, card.months, car.name, car.order, car.months) == (
        "Credit card", 1, 7, "Car loan", 2, 22,
    )  # fmt: skip
    assert card.interest == 935_880  # ₱9,358.80, the engine's figure
    assert card.paid == 8_623_880  # ₱86,238.80
    assert car.interest == 3_891_435
    assert car.paid == 44_034_498
    assert [r.on for r in card.rows[:2]] == [date(2027, 1, 1), date(2027, 2, 1)]
    assert (
        card.rows[-1].on == date(2027, 7, 1) == view.run.value("debt.payoff_date", card.entity_id)
    )
    # The card's whole ₱12,550.00 rolls to the car loan the month after it is paid off.
    rolled = [r for r in car.rows if r.rolled_in]
    assert [(r.on, r.rolled_in, r.payment) for r in rolled] == [
        (date(2027, 8, 1), 1_255_000, 2_495_000)
    ]
    assert car.rows[6].payment == 1_240_000


def test_month_one_from_sep_15_is_the_oct_15_statement(house: Villanueva) -> None:
    card, car = _view(house, SEP_15).schedules
    assert (card.rows[0].on, card.rows[0].left) == (date(2026, 10, 15), 8_100_000)  # ₱81,000.00
    assert (car.rows[0].on, car.rows[0].left) == (date(2026, 10, 15), 41_075_000)  # ₱410,750.00


@pytest.mark.parametrize("seed", SEEDS)
def test_every_schedule_matches_the_engine(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded so a failure repeats; not for security
    entities, facts = _household(rng)
    on = date(2026, 9, 15)
    snapshot = take_snapshot(HOUSEHOLD, facts, on)
    run = compute(snapshot, entities)
    view = money_view(snapshot, entities)
    for schedule in view.schedules:
        owed = schedule.balance
        for row in schedule.rows:
            assert row.owed == owed
            assert row.left == row.owed + row.interest - row.payment
            assert row.principal == row.payment - row.interest
            owed = row.left
        assert schedule.order == run.value("debt.strategy_order", schedule.entity_id)
        assert schedule.months == run.value("debt.payoff_months", schedule.entity_id)
        if schedule.months is None:
            assert len(schedule.rows) <= NEVER_ROWS
        else:
            assert len(schedule.rows) == schedule.months
            assert schedule.rows[-1].left == 0
            assert schedule.interest == run.value("debt.total_interest", schedule.entity_id)
            assert schedule.paid == schedule.balance + schedule.interest
    # The plan's lines end on the engine's unallocated figure, and the split adds up to the pay.
    if view.lines and view.lines[-1].left is not None:
        assert view.lines[-1].left == run.value("plan.unallocated")
    if view.split is not None:
        s = view.split
        assert s.needs + s.wants + s.debt + s.savings + s.unplanned - s.over == s.total


def test_what_the_household_owns_and_owes(house: Villanueva) -> None:
    standing = _view(house, DEC_1).standing
    assert [(h.name, h.amount, h.since) for h in standing.owns] == [
        ("Emergency fund", 16_010_000, date(2026, 11, 15)),
        ("Long-term savings", 3_000_000, date(2026, 8, 1)),
        ("House fund", 0, date(2026, 12, 1)),
    ]
    assert [h.name for h in standing.owes] == ["Credit card", "Car loan"]  # strategy order
    assert (standing.owned, standing.owed, standing.net) == (19_010_000, 47_831_063, -28_821_063)


def test_the_milestones_soonest_first(house: Villanueva) -> None:
    found = [(m.kind, m.name, m.on, m.months, m.on_track) for m in _view(house, DEC_1).milestones]
    assert found == [
        ("emergency_fund", "Emergency fund", date(2027, 5, 1), 5, None),
        ("debt_paid", "Credit card", date(2027, 7, 1), 7, None),
        ("debt_paid", "Car loan", date(2028, 10, 1), 22, None),
        ("goal_reached", "House fund", date(2031, 12, 1), 60, True),
    ]


def test_the_plan_before_its_last_change(house: Villanueva) -> None:
    snapshot = take_snapshot(HOUSEHOLD, house.facts, DEC_1)
    assert plan_before(house.facts, snapshot) == date(2026, 11, 30)
    screen = money_screen(house.facts, house.entities, HOUSEHOLD, DEC_1)
    assert screen.plan.label == "From Dec 1, 2026"
    assert screen.before is not None
    assert screen.before.label == "Before Dec 1, 2026"
    changed = {line.name: line.change for line in screen.plan.lines if line.change}
    assert changed == {
        "Mara's salary": "was ₱52,000.00",
        "Credit card, extra": "was ₱4,000.00",
        "Emergency fund": "was ₱5,050.00",
        "House fund": "new",
    }
    assert [line.left for line in screen.before.lines][-1] == "₱0.00"
    assert screen.before.lines[1].left == "₱100,000.00"


def test_no_version_before_when_the_plan_never_changed() -> None:
    salary = entity("income", "Ana's salary")
    facts = [fact(salary.id, "income.monthly_net", 5_000_000, "2026-03-01")]
    snapshot = take_snapshot(HOUSEHOLD, facts, date(2026, 9, 1))
    assert plan_before(facts, snapshot) is None
    screen = money_screen(facts, [salary], HOUSEHOLD, date(2026, 9, 1))
    assert screen.before is None
    assert screen.plan.label == "On Sep 1, 2026"


def test_the_screen_on_dec_1_in_words(house: Villanueva) -> None:
    screen = money_screen(house.facts, house.entities, HOUSEHOLD, DEC_1)
    assert [(t.label, t.value, t.negative) for t in screen.tiles] == [
        ("Total salary", "₱116,000.00", False),
        ("Free after expenses", "₱25,050.00", False),
        ("Emergency cover", "2.3 months", False),
        ("Net worth", "-₱288,210.63", True),
    ]
    assert screen.split is not None
    assert [(p.label, p.text, p.share) for p in screen.split.parts] == [
        ("Needs", "₱70,000.00", "60%"),
        ("Wants", "₱6,000.00", "5%"),
        ("Debt", "₱24,950.00", "22%"),
        ("Savings", "₱15,050.00", "13%"),
    ]
    card, car = screen.debts
    assert (card.rate, card.paying, card.extra, card.payoff_in, card.interest_left) == (
        "3% a month", "₱12,550.00", "₱10,000.00", "7 months", "₱9,358.80",
    )  # fmt: skip
    assert (card.paid_total, card.interest_total, card.principal_total) == (
        "₱86,238.80", "₱9,358.80", "₱76,880.00",
    )  # fmt: skip
    assert (car.rate, car.paying, car.extra, car.payoff_on) == (
        "9% a year", "₱12,400.00", None, date(2028, 10, 1),
    )  # fmt: skip
    assert [r.rolled_in for r in car.rows if r.rolled_in] == ["₱12,550.00"]
    assert car.rows[0].fill < 1
    assert car.rows[-1].fill == 0
    assert [(m.title, m.value, m.month_only) for m in screen.moments] == [
        ("Jun's salary (13th-month pay)", "₱48,000.00", True)
    ]


def test_what_takes_effect_later_is_a_big_moment(house: Villanueva) -> None:
    """On Nov 20, Mara's new salary and the new plan start on Dec 1: ahead of the household."""
    screen = money_screen(house.facts, house.entities, HOUSEHOLD, NOV_20)
    ahead = [(m.on, m.title, m.value) for m in screen.moments if m.kind == "ahead"]
    assert (date(2026, 12, 1), "Mara's salary (take-home pay a month)", "₱68,000.00") in ahead
    assert all(on > NOV_20 for on, _, _ in ahead)


def test_a_missing_amount_leaves_what_follows_unknown() -> None:
    salary, rent = entity("income", "Ana's salary"), entity("expense", "Rent")
    facts = [
        fact(salary.id, "income.monthly_net", 5_000_000, "2026-03-01"),
        fact(rent.id, "expense.essential", "yes", "2026-03-01"),
    ]
    inputs = Inputs(take_snapshot(HOUSEHOLD, facts, date(2026, 9, 1)), [salary, rent])
    lines = plan_lines(inputs)
    assert [(line.amount, line.left) for line in lines] == [(5_000_000, 5_000_000), (None, None)]
    assert split_of(lines) is None


def test_a_debt_that_never_pays_off_keeps_a_year_of_rows() -> None:
    card = entity("debt", "Card")
    facts = [
        fact(card.id, "debt.balance", 10_000_000, "2026-03-01"),
        fact(card.id, "debt.monthly_rate", Decimal("0.03"), "2026-03-01"),
        fact(card.id, "debt.minimum_payment", 100_000, "2026-03-01"),  # less than the interest
    ]
    snapshot = take_snapshot(HOUSEHOLD, facts, date(2026, 9, 1))
    (schedule,) = debt_schedules(Inputs(snapshot, [card]))
    assert schedule.months is None
    assert 0 < len(schedule.rows) <= NEVER_ROWS
    (view,) = money_screen(facts, [card], HOUSEHOLD, date(2026, 9, 1)).debts
    assert view.why_not == "never paid off at this payment"
    assert view.paid_total is None


def test_no_schedule_without_a_strategy_for_two_debts() -> None:
    debts = [entity("debt", "Card"), entity("debt", "Loan")]
    facts = [
        f
        for d in debts
        for f in (
            fact(d.id, "debt.balance", 1_000_000, "2026-03-01"),
            fact(d.id, "debt.monthly_rate", Decimal("0.01"), "2026-03-01"),
            fact(d.id, "debt.minimum_payment", 200_000, "2026-03-01"),
        )
    ]
    snapshot = take_snapshot(HOUSEHOLD, facts, date(2026, 9, 1))
    assert debt_schedules(Inputs(snapshot, debts)) == ()
    screen = money_screen(facts, debts, HOUSEHOLD, date(2026, 9, 1))
    assert {d.why_not for d in screen.debts} == {"no payoff strategy chosen"}
    assert all(not d.rows for d in screen.debts)


def test_household_ids_never_mix() -> None:
    other = uuid.uuid4()
    salary = entity("income", "Ana's salary")
    facts = [fact(salary.id, "income.monthly_net", 5_000_000, "2026-03-01", household_id=other)]
    screen = money_screen(facts, [salary], HOUSEHOLD, date(2026, 9, 1))
    # Another household's fact is never read: this household's salary is unknown, not ₱50,000.
    assert [(line.name, line.amount) for line in screen.plan.lines] == [("Ana's salary", None)]
