"""Properties the engine holds for any household, on seeded random inputs (no new dependency).

Phase 2, task 3: "property tests hold (for example, payments made equal the starting balance plus
interest)". Each test draws its cases from `random.Random(seed)`, so a failure always repeats.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from kako.engine import Override, compute
from kako.engine.arith import interest, ratio
from kako.engine.dates import HORIZON_MONTHS, add_months, whole_months_until
from kako.engine.debts import Debt, simulate, strategy_order
from kako.facts.snapshot import take_snapshot
from tests.support.facts import HOUSEHOLD, entity, fact

SEEDS = range(40)


def _rng(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311 - seeded so a failure repeats; not for security


def _debt(rng: random.Random, name: str) -> Debt:
    balance = rng.randint(1, 50_000_000)
    rate = Decimal(rng.randint(0, 60_000)) / Decimal(1_000_000)  # 0% to 6% a month
    minimum = rng.randint(0, balance // 10 + 1)
    extra = rng.choice([0, 0, rng.randint(1, 2_000_000)])
    return Debt(uuid.uuid4(), name, balance, rate, minimum, extra)


def _reference_interest(balance: int, rate: Decimal) -> int:
    """Half up, by exact fractions: an independent check of the engine's rounding."""
    exact = Fraction(balance) * Fraction(rate)
    return int(exact + Fraction(1, 2)) if exact >= 0 else -int(-exact + Fraction(1, 2))


@pytest.mark.parametrize("seed", SEEDS)
def test_interest_rounds_half_up(seed: int) -> None:
    rng = _rng(seed)
    for _ in range(200):
        balance = rng.randint(0, 10**12)
        rate = Decimal(rng.randint(0, 1_000_000)) / Decimal(1_000_000)
        assert interest(balance, rate) == _reference_interest(balance, rate)


@pytest.mark.parametrize("seed", SEEDS)
def test_one_debt_payments_equal_balance_plus_interest(seed: int) -> None:
    rng = _rng(seed)
    for _ in range(25):
        debt = _debt(rng, "D")
        payoff = simulate([debt])[debt.entity_id]
        first = interest(debt.balance, debt.monthly_rate)
        payment = debt.minimum + debt.extra
        if payment <= first:
            assert payoff.never  # the doc's rule for one debt
            continue
        if payoff.never:  # pays down, but not within 100 years
            assert len(payoff.payments) == HORIZON_MONTHS
            continue
        assert payoff.months == len(payoff.payments)
        assert payoff.total_interest == sum(payoff.interest)
        assert sum(payoff.payments) == debt.balance + payoff.total_interest
        assert all(p == payment for p in payoff.payments[:-1])  # full payments, then the rest
        assert 0 < payoff.payments[-1] <= payment


@pytest.mark.parametrize("seed", SEEDS)
def test_more_extra_never_takes_longer_or_costs_more(seed: int) -> None:
    rng = _rng(seed)
    for _ in range(20):
        debt = _debt(rng, "D")
        more = Debt(debt.entity_id, "D", debt.balance, debt.monthly_rate, debt.minimum,
                    debt.extra + rng.randint(1, 1_000_000))  # fmt: skip
        a, b = simulate([debt])[debt.entity_id], simulate([more])[debt.entity_id]
        if a.never:
            continue
        assert b.months is not None
        assert b.total_interest is not None
        assert b.months <= a.months  # type: ignore[operator]
        assert b.total_interest <= a.total_interest  # type: ignore[operator]


@pytest.mark.parametrize("seed", SEEDS)
def test_many_debts_with_the_rollover(seed: int) -> None:
    """Every paid-off debt's payments equal its balance plus interest; no month pays more than the
    household's debt budget (every minimum plus every extra); and the budget is never lost: while
    any debt is open, the month's payments fall short of it only by what a final payment saved."""
    rng = _rng(seed)
    debts = [_debt(rng, f"D{i}") for i in range(rng.randint(2, 5))]
    ordered = strategy_order(debts, rng.choice(["avalanche", "snowball"]))
    payoffs = simulate(ordered)
    budget = sum(d.minimum + d.extra for d in debts)
    longest = max(len(p.payments) for p in payoffs.values())
    for month in range(longest):
        paid = sum(p.payments[month] for p in payoffs.values() if month < len(p.payments))
        assert paid <= budget
    for d in debts:
        p = payoffs[d.entity_id]
        if not p.never:
            assert sum(p.payments) == d.balance + p.total_interest  # type: ignore[operator]
            assert p.months == len(p.payments)
    # The debts behind a debt in the order can only help it: one of them paid off first rolls its
    # payment forward. So no debt is paid off later than it would be without them.
    for i, d in enumerate(ordered):
        alone = simulate(ordered[: i + 1])[d.entity_id]
        together = payoffs[d.entity_id]
        if alone.months is not None:
            assert together.months is not None
            assert together.months <= alone.months


@pytest.mark.parametrize("seed", SEEDS)
def test_calendar_months(seed: int) -> None:
    rng = _rng(seed)
    for _ in range(50):
        start = date(2026, 1, 1) + timedelta(days=rng.randint(0, 3650))
        k = rng.randint(0, 240)
        landed = add_months(start, k)
        assert landed.day <= start.day
        assert whole_months_until(start, landed) == k
        assert whole_months_until(start, landed - timedelta(days=1)) == max(k - 1, 0)


def _household(rng: random.Random) -> tuple[list, list]:  # type: ignore[type-arg]
    entities, facts = [], []

    def add(kind: str, values: dict[str, object]) -> None:
        row = entity(kind, f"{kind}-{len(entities)}")
        entities.append(row)
        facts.extend(fact(row.id, k, v, "2026-03-01") for k, v in values.items())  # type: ignore[arg-type]

    for _ in range(rng.randint(0, 3)):
        add("income", {"income.monthly_net": rng.randint(0, 20_000_000)})
    for _ in range(rng.randint(0, 4)):
        add("expense", {"expense.monthly_amount": rng.randint(0, 5_000_000),
                        "expense.essential": rng.choice(["yes", "no"])})  # fmt: skip
    for _ in range(rng.randint(0, 3)):
        add("debt", {"debt.balance": rng.randint(0, 50_000_000),
                     "debt.monthly_rate": Decimal(rng.randint(0, 40_000)) / Decimal(1_000_000),
                     "debt.minimum_payment": rng.randint(0, 3_000_000),
                     "plan.allocation": rng.randint(0, 1_000_000)})  # fmt: skip
    purposes = ["emergency"] + ["general"] * 3
    rng.shuffle(purposes)
    for purpose in purposes[: rng.randint(0, 3)]:
        add("account", {"account.balance": rng.randint(0, 30_000_000),
                        "account.liquid": rng.choice(["yes", "no"]), "account.purpose": purpose,
                        "plan.allocation": rng.randint(0, 1_000_000)})  # fmt: skip
    for _ in range(rng.randint(0, 2)):
        add("goal", {"goal.target_amount": rng.randint(0, 50_000_000),
                     "goal.saved_amount": rng.randint(0, 10_000_000),
                     "goal.target_date": date(2026, 9, 15) + timedelta(days=rng.randint(-60, 4000)),
                     "plan.allocation": rng.randint(0, 2_000_000)})  # fmt: skip
    facts.append(fact(None, "household.emergency_months_target", rng.randint(1, 24), "2026-03-01"))
    facts.append(fact(None, "preference.debt_strategy", rng.choice(["avalanche", "snowball"]),
                      "2026-03-01"))  # fmt: skip
    return entities, facts


@pytest.mark.parametrize("seed", SEEDS)
def test_household_identities_and_order_independence(seed: int) -> None:
    rng = _rng(seed)
    entities, facts = _household(rng)
    on = date(2026, 9, 15)
    run = compute(take_snapshot(HOUSEHOLD, facts, on), entities)

    income = run.value("cashflow.monthly_income")
    expenses = run.value("cashflow.monthly_expenses")
    minimums = run.value("cashflow.minimum_payments")
    assert run.value("cashflow.monthly_surplus") == income - expenses - minimums  # type: ignore[operator]
    # Every entity here is open, and only debts, accounts and goals carry an allocation.
    allocations = sum(f.value_money or 0 for f in facts if f.attribute == "plan.allocation")
    assert run.value("plan.unallocated") == run.value("cashflow.monthly_surplus") - allocations  # type: ignore[operator]
    if income:
        assert run.value("cashflow.debt_payment_share") == ratio(minimums, income)  # type: ignore[arg-type]

    for figure in run.figures:
        assert (figure.value is None) <= (figure.flag is not None)
        if figure.unit == "ratio" and isinstance(figure.value, Decimal):
            assert figure.value == figure.value.quantize(Decimal("0.000001"))
        if figure.unit in ("centavos", "months", "count") and figure.value is not None:
            assert isinstance(figure.value, int)
        if figure.unit == "months" and figure.value is not None:
            assert 0 <= figure.value <= HORIZON_MONTHS  # type: ignore[operator]

    shuffled_facts, shuffled_entities = facts[:], entities[:]
    rng.shuffle(shuffled_facts)
    rng.shuffle(shuffled_entities)
    again = compute(take_snapshot(HOUSEHOLD, shuffled_facts, on), shuffled_entities)
    assert again == run


@pytest.mark.parametrize("seed", SEEDS)
def test_an_override_equal_to_the_fact_changes_no_value(seed: int) -> None:
    rng = _rng(seed)
    entities, facts = _household(rng)
    on = date(2026, 9, 15)
    snapshot = take_snapshot(HOUSEHOLD, facts, on)
    chosen = rng.choice([f for f in facts if f.attribute == "household.emergency_months_target"])
    same = Override(uuid.uuid4(), None, chosen.attribute, chosen.value, on)
    plain, what_if = compute(snapshot, entities), compute(snapshot, entities, [same])
    assert [(f.key, f.entity_id, f.value, f.flag) for f in plain.figures] == [
        (f.key, f.entity_id, f.value, f.flag) for f in what_if.figures
    ]
