"""Every figure of the worked example (docs/data-model.md, "Worked example: a new job"), exactly.

Phase 2, task 3, done when: a test reproduces every figure of the worked example exactly.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from kako.engine import Override, Run, compute
from kako.facts.snapshot import take_snapshot
from tests.support.facts import HOUSEHOLD
from tests.support.villanueva import DEC_1, SEP_15, Villanueva, build


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _run(h: Villanueva, on: date, **allocations: int) -> Run:
    """The plan on `on`; keyword allocations are a what-if (entity key=centavos a month)."""
    overrides = [
        Override(uuid.uuid4(), h.ids[key], "plan.allocation", amount, on)
        for key, amount in allocations.items()
    ]
    return compute(take_snapshot(HOUSEHOLD, h.facts, on), h.entities, overrides)


def test_plan_v2_on_sep_15(house: Villanueva) -> None:
    run = _run(house, SEP_15)
    card = house.ids["card"]
    assert run.value("cashflow.monthly_income") == 10_000_000  # ₱100,000
    assert run.value("cashflow.monthly_expenses") == 7_600_000  # ₱76,000
    assert run.value("cashflow.essential_expenses") == 7_000_000  # ₱70,000
    assert run.value("cashflow.minimum_payments") == 1_495_000  # ₱14,950
    assert run.value("cashflow.monthly_surplus") == 905_000  # ₱9,050
    assert run.value("cashflow.debt_payment_share") == Decimal("0.149500")
    assert run.value("cashflow.savings_rate") == Decimal("0.050500")
    # ₱150,000 ÷ ₱70,000: a runway of 2.1 months (the long-term savings aren't liquid).
    assert run.value("savings.emergency_runway_months") == Decimal("2.142857")
    assert run.value("savings.emergency_target") == 21_000_000  # 3 months, ₱210,000
    # ⌈₱60,000 ÷ ₱5,050⌉ = 12 months (the doc said 10 before task 3; corrected).
    assert run.value("savings.months_to_target") == 12
    # Option B: the card is paid off in 17 months, with ₱24,303.62 of interest.
    assert run.value("debt.strategy_order", card) == 1  # 3% a month beats 9% a year
    assert run.value("debt.payoff_months", card) == 17
    assert run.value("debt.total_interest", card) == 2_430_362
    assert run.value("debt.payoff_date", card) == date(2028, 2, 15)
    assert run.value("plan.unallocated") == 0
    assert run.get("savings.months_to_target").flag is None
    assert "cashflow.thirteenth_month" not in {f.key for f in run.figures}  # December only
    # The car loan (9% a year, chosen here) is second, and gets the card's ₱6,550 from month 18.
    car = house.ids["car"]
    assert run.value("debt.strategy_order", car) == 2
    assert run.value("debt.payoff_months", car) == 32
    assert run.value("debt.total_interest", car) == 5_833_322


def test_plan_v2_option_a_and_minimum_only(house: Villanueva) -> None:
    card = house.ids["card"]
    a = _run(house, SEP_15, card=905_000, fund=0)
    assert a.value("debt.payoff_months", card) == 9
    assert a.value("debt.total_interest", card) == 1_246_010  # ₱12,460.10
    assert a.get("savings.months_to_target").flag == "no_allocation"
    assert a.value("plan.unallocated") == 0

    # Minimum only: ₱2,550 only covers the card's interest, so its balance stands still until the
    # car loan is paid off (month 40) and its ₱12,400 rolls over to the card (Pim, Nov 17).
    minimum = _run(house, SEP_15, card=0, fund=0)
    car = house.ids["car"]
    assert minimum.value("debt.payoff_months", car) == 40
    assert minimum.value("debt.payoff_months", card) == 47
    assert minimum.value("debt.total_interest", card) == 11_163_547  # ₱111,635.47


def test_plan_v3_on_dec_1(house: Villanueva) -> None:
    run = _run(house, DEC_1)
    card, house_fund = house.ids["card"], house.ids["house"]
    assert run.value("cashflow.monthly_income") == 11_600_000  # ₱116,000
    assert run.value("cashflow.thirteenth_month") == 4_800_000  # Jun's, in December
    assert run.value("cashflow.monthly_surplus") == 2_505_000  # ₱25,050
    assert run.value("plan.unallocated") == 0
    # The card: ₱76,880.00 after the Nov statement, ₱10,000 extra: 7 months, ₱9,358.80.
    assert run.value("debt.payoff_months", card) == 7
    assert run.value("debt.total_interest", card) == 935_880
    assert run.value("debt.payoff_date", card) == date(2027, 7, 1)
    # Runway 2.3 months (₱160,100 ÷ ₱70,000); the 3-month target in 5 months, not 12.
    assert run.value("savings.emergency_runway_months") == Decimal("2.287143")
    assert run.value("savings.months_to_target") == 5
    # The house fund (target chosen here): ₱300,000 by Dec 1, 2031 at ₱5,050 a month.
    assert run.value("goal.months_to_target", house_fund) == 60
    assert run.value("goal.projected_date", house_fund) == date(2031, 12, 1)
    assert run.value("goal.required_monthly", house_fund) == 500_000
    assert run.value("goal.on_track", house_fund) == 1
    car = house.ids["car"]
    assert run.value("debt.payoff_months", car) == 23
    assert run.value("debt.total_interest", car) == 4_224_098


def test_plan_v3_all_extra_on_the_card(house: Villanueva) -> None:
    card = house.ids["card"]
    run = _run(house, DEC_1, card=2_505_000, fund=0, house=0)
    assert run.value("debt.payoff_months", card) == 3
    assert run.value("debt.total_interest", card) == 462_001  # ₱4,620.01
    assert run.get("goal.months_to_target", house.ids["house"]).flag == "no_allocation"


def test_the_card_balance_after_two_payments(house: Villanueva) -> None:
    """₱85,000 at 3%, two payments of ₱6,550 (option B): ₱76,880.00, the Nov statement."""
    run = _run(house, SEP_15)
    del run  # the engine's months are checked above; this is the arithmetic the doc states
    balance = 8_500_000
    for _ in range(2):
        balance += (balance * 3 + 50) // 100  # 3%, half up (exact here)
        balance -= 655_000
    assert balance == 7_688_000
