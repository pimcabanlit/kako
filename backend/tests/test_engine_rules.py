"""The engine's rules beyond the worked example: flags, missing facts, strategy order, rollover,
goals, what-ifs, traceability, and the arithmetic helpers."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, get_args

import pytest

from kako.db.enums import ENUMS
from kako.engine import EngineInputError, Override, Run, compute
from kako.engine.arith import ceil_div, interest, ratio, round_half_up
from kako.engine.dates import add_months, whole_months_until
from kako.engine.figures import FigureRef, Flag, Unit
from kako.facts.model import EntityRow, FactRow
from kako.facts.snapshot import take_snapshot
from tests.support.facts import HOUSEHOLD, entity, fact

ON = date(2026, 9, 15)


class Household:
    """A tiny household built fact by fact; nothing is filled in for you."""

    def __init__(self) -> None:
        self.entities: list[EntityRow] = []
        self.facts: list[FactRow] = []

    def add(self, kind: str, name: str, values: dict[str, Any], **extra: Any) -> uuid.UUID:
        row = entity(kind, name, **extra)
        self.entities.append(row)
        for attribute, value in values.items():
            self.facts.append(fact(row.id, attribute, value, "2026-03-01"))
        return row.id

    def household(self, attribute: str, value: Any) -> FactRow:
        row = fact(None, attribute, value, "2026-03-01")
        self.facts.append(row)
        return row

    def run(self, on: date = ON, overrides: list[Override] | None = None) -> Run:
        return compute(take_snapshot(HOUSEHOLD, self.facts, on), self.entities, overrides or [])


def _basic() -> Household:
    h = Household()
    h.add("income", "Salary", {"income.monthly_net": 5_000_000})
    h.add("expense", "Rent", {"expense.monthly_amount": 2_000_000, "expense.essential": "yes"})
    return h


def _debt(balance: int, rate: str, minimum: int, extra: int = 0) -> dict[str, Any]:
    values: dict[str, Any] = {
        "debt.balance": balance,
        "debt.monthly_rate": Decimal(rate),
        "debt.minimum_payment": minimum,
    }
    if extra:
        values["plan.allocation"] = extra
    return values


# --- Enumerations ------------------------------------------------------------------------------


def test_units_and_flags_match_the_database() -> None:
    assert set(get_args(Unit)) == set(ENUMS[("figure", "unit")])
    assert set(get_args(Flag)) == set(ENUMS[("figure", "flag")])


# --- Cash flow flags ---------------------------------------------------------------------------


def test_a_missing_fact_is_never_assumed() -> None:
    h = _basic()
    h.add("income", "Side job", {})  # an income with no monthly_net
    run = h.run()
    for key in ("cashflow.monthly_income", "cashflow.monthly_surplus", "plan.unallocated"):
        figure = run.get(key)
        assert (figure.value, figure.flag) == (None, "missing_input"), key
    assert run.get("cashflow.debt_payment_share").flag == "missing_input"
    assert run.value("cashflow.monthly_expenses") == 2_000_000  # unaffected


def test_no_income_and_no_essential_expenses() -> None:
    h = Household()
    h.add("expense", "Fun", {"expense.monthly_amount": 100_000, "expense.essential": "no"})
    h.add("account", "Cash", {"account.balance": 1, "account.liquid": "yes",
                               "account.purpose": "general"})  # fmt: skip
    run = h.run()
    assert run.value("cashflow.monthly_income") == 0
    assert run.get("cashflow.debt_payment_share").flag == "no_income"
    assert run.get("cashflow.savings_rate").flag == "no_income"
    assert run.value("cashflow.essential_expenses") == 0
    assert run.get("savings.emergency_runway_months").flag == "no_essential_expenses"


def test_a_negative_surplus_is_shown_and_flagged() -> None:
    h = _basic()
    h.add("expense", "Hospital", {"expense.monthly_amount": 4_000_000, "expense.essential": "yes"})
    h.add("account", "Fund", {"account.balance": 0, "account.liquid": "yes",
                               "account.purpose": "emergency", "plan.allocation": 1})  # fmt: skip
    run = h.run()
    surplus = run.get("cashflow.monthly_surplus")
    assert (surplus.value, surplus.flag) == (-1_000_000, "negative")
    left = run.get("plan.unallocated")
    assert (left.value, left.flag) == (-1_000_001, "negative")


def test_thirteenth_month_pay_only_in_december() -> None:
    h = _basic()
    h.add("income", "Bonus job", {"income.monthly_net": 1, "income.thirteenth_month": 900_000})
    assert "cashflow.thirteenth_month" not in {f.key for f in h.run().figures}
    assert h.run(date(2026, 12, 15)).value("cashflow.thirteenth_month") == 900_000


def test_closed_and_not_yet_opened_entities_are_left_out() -> None:
    h = _basic()
    h.add("income", "Old job", {"income.monthly_net": 999}, closed_on=date(2026, 9, 1))
    h.add("income", "Next job", {"income.monthly_net": 999}, opened_on=date(2026, 10, 1))
    h.add("income", "Ends today", {"income.monthly_net": 999}, closed_on=ON)  # closed_on excludes
    assert h.run().value("cashflow.monthly_income") == 5_000_000


# --- Savings -----------------------------------------------------------------------------------


def _with_fund(h: Household, balance: int, allocation: int | None = 100_000) -> uuid.UUID:
    values: dict[str, Any] = {"account.balance": balance, "account.liquid": "yes",
                              "account.purpose": "emergency"}  # fmt: skip
    if allocation is not None:
        values["plan.allocation"] = allocation
    h.household("household.emergency_months_target", 3)
    return h.add("account", "Fund", values)


def test_months_to_target() -> None:
    h = _basic()
    _with_fund(h, 5_000_000)  # target ₱60,000, ₱50,000 saved, ₱1,000 a month
    assert h.run().value("savings.months_to_target") == 10
    h2 = _basic()
    _with_fund(h2, 6_500_000, allocation=None)  # already past the target: 0, allocation or not
    assert h2.run().value("savings.months_to_target") == 0
    h3 = _basic()
    _with_fund(h3, 0, allocation=None)
    assert h3.run().get("savings.months_to_target").flag == "no_allocation"
    h4 = _basic()
    h4.household("household.emergency_months_target", 3)
    h4.add("account", "Wallet", {"account.balance": 0, "account.liquid": "yes",
                                 "account.purpose": "general"})  # fmt: skip
    assert h4.run().get("savings.months_to_target").flag == "no_emergency_account"
    h5 = _basic()
    h5.add("account", "Wallet", {"account.balance": 0, "account.liquid": "yes"})
    h5.household("household.emergency_months_target", 3)
    assert h5.run().get("savings.months_to_target").flag == "missing_input"


def test_two_emergency_funds_are_refused() -> None:
    h = _basic()
    _with_fund(h, 1)
    h.add("account", "Second", {"account.balance": 1, "account.liquid": "yes",
                                "account.purpose": "emergency"})  # fmt: skip
    with pytest.raises(EngineInputError, match="V-16"):
        h.run()


# --- Debts -------------------------------------------------------------------------------------


def test_a_debt_whose_payment_only_covers_interest_never_pays_off() -> None:
    h = _basic()
    card = h.add("debt", "Card", _debt(8_500_000, "0.03", 255_000))
    run = h.run()
    for key in ("debt.payoff_months", "debt.total_interest", "debt.payoff_date"):
        figure = run.get(key, card)
        assert (figure.value, figure.flag) == (None, "never_pays_off")
    assert run.value("debt.strategy_order", card) == 1  # one debt needs no strategy


def test_two_debts_need_a_strategy() -> None:
    h = _basic()
    card = h.add("debt", "Card", _debt(1_000_000, "0.03", 100_000))
    loan = h.add("debt", "Loan", _debt(5_000_000, "0.01", 200_000))
    run = h.run()
    for debt in (card, loan):
        assert run.get("debt.strategy_order", debt).flag == "strategy_missing"
        assert run.get("debt.payoff_months", debt).flag == "strategy_missing"
    h.household("preference.debt_strategy", "snowball")
    assert h.run().value("debt.strategy_order", card) == 1  # smallest balance first


def test_avalanche_and_snowball_order() -> None:
    h = _basic()
    small = h.add("debt", "Small, cheap", _debt(100_000, "0.01", 10_000))
    big = h.add("debt", "Big, dear", _debt(900_000, "0.03", 50_000))
    loan = h.add("debt", "Loan", {"debt.balance": 500_000, "debt.annual_rate": Decimal("0.24"),
                                  "debt.minimum_payment": 30_000})  # 2% a month  # fmt: skip
    strategy = h.household("preference.debt_strategy", "avalanche")
    run = h.run()
    assert [run.value("debt.strategy_order", d) for d in (big, loan, small)] == [1, 2, 3]
    h.facts.remove(strategy)
    h.household("preference.debt_strategy", "snowball")
    run = h.run()
    assert [run.value("debt.strategy_order", d) for d in (small, loan, big)] == [1, 2, 3]


def test_a_paid_off_debt_rolls_its_whole_payment_over() -> None:
    """Debt A: ₱1,000 at 0%, ₱400 + ₱200 extra a month. Debt B: ₱5,000 at 0%, ₱100 a month.
    A is paid in 2 months (600, 400). From month 3, B gets 100 + 600 = 700: 100, 100, then 700s."""
    h = _basic()
    h.household("preference.debt_strategy", "snowball")
    a = h.add("debt", "A", _debt(100_000, "0", 40_000, extra=20_000))
    b = h.add("debt", "B", _debt(500_000, "0", 10_000))
    run = h.run()
    assert run.value("debt.payoff_months", a) == 2
    # B: 100 + 100 = 200 in two months, 4,800 left at 700 a month: 7 more months.
    assert run.value("debt.payoff_months", b) == 9
    assert run.value("debt.total_interest", b) == 0
    assert run.value("debt.payoff_date", b) == date(2027, 6, 15)


def test_an_annual_rate_is_divided_by_twelve_then_rounded_once() -> None:
    h = _basic()
    loan = h.add("debt", "Loan", {"debt.balance": 1_000_000, "debt.annual_rate": Decimal("0.07"),
                                  "debt.minimum_payment": 1_100_000})  # fmt: skip
    # 1,000,000 * 0.07 / 12 = 5,833.33... rounds to 5,833 centavos, then paid off in one month.
    run = h.run()
    assert run.value("debt.payoff_months", loan) == 1
    assert run.value("debt.total_interest", loan) == 5_833


def test_a_debt_with_both_rates_is_refused() -> None:
    h = _basic()
    values = _debt(100_000, "0.01", 10_000) | {"debt.annual_rate": Decimal("0.12")}
    h.add("debt", "Odd", values)
    with pytest.raises(EngineInputError, match="one"):
        h.run()


def test_a_missing_balance_flags_every_debt_figure() -> None:
    h = _basic()
    card = h.add("debt", "Card", {"debt.monthly_rate": Decimal("0.03"),
                                  "debt.minimum_payment": 10_000})  # fmt: skip
    run = h.run()
    assert run.get("cashflow.minimum_payments").flag == "missing_input"
    for key in ("debt.strategy_order", "debt.payoff_months", "debt.total_interest"):
        assert run.get(key, card).flag == "missing_input"


def test_a_paid_off_debt_has_no_payoff_figures() -> None:
    h = _basic()
    done = h.add("debt", "Done", _debt(0, "0.03", 0))
    run = h.run()
    assert run.value("cashflow.minimum_payments") == 0
    assert all(f.entity_id != done for f in run.figures)


def test_a_missing_debt_fact_flags_every_debt() -> None:
    h = _basic()
    h.household("preference.debt_strategy", "avalanche")
    card = h.add("debt", "Card", _debt(100_000, "0.03", 10_000))
    h.add("debt", "Loan", {"debt.balance": 100_000, "debt.minimum_payment": 10_000})  # no rate
    run = h.run()
    assert run.get("debt.payoff_months", card).flag == "missing_input"
    assert run.value("cashflow.minimum_payments") == 20_000  # the minimums are all there


# --- Goals -------------------------------------------------------------------------------------


def _goal(h: Household, **values: Any) -> uuid.UUID:
    base: dict[str, Any] = {"goal.target_amount": 1_200_000, "goal.saved_amount": 200_000,
                            "goal.target_date": date(2027, 9, 15)}  # fmt: skip
    base.update(values)
    return h.add("goal", "Trip", {k: v for k, v in base.items() if v is not None})


def test_goal_figures() -> None:
    h = _basic()
    trip = _goal(h, **{"plan.allocation": 90_000})
    run = h.run()
    assert run.value("goal.months_to_target", trip) == 12  # ⌈₱10,000 ÷ ₱900⌉
    assert run.value("goal.projected_date", trip) == date(2027, 9, 15)
    assert run.value("goal.required_monthly", trip) == 83_334  # ⌈₱10,000 ÷ 12⌉
    assert run.value("goal.on_track", trip) == 1


def test_a_goal_already_reached_past_due_or_unfunded() -> None:
    h = _basic()
    done = _goal(h, **{"goal.saved_amount": 1_200_000})
    late = _goal(h, **{"goal.target_date": date(2026, 10, 1), "plan.allocation": 1})
    idle = _goal(h)
    run = h.run()
    assert run.value("goal.months_to_target", done) == 0
    assert run.value("goal.projected_date", done) == ON
    assert run.value("goal.required_monthly", done) == 0
    assert run.value("goal.on_track", done) == 1
    assert run.get("goal.required_monthly", late).flag == "past_due"  # no payday before Oct 1
    assert run.value("goal.on_track", late) == 0
    assert run.get("goal.months_to_target", idle).flag == "no_allocation"
    idle_track = run.get("goal.on_track", idle)
    assert (idle_track.value, idle_track.flag) == (0, "no_allocation")
    assert run.get("goal.months_to_target", late).flag == "no_allocation"  # ₱0.01: 1M months


# --- What-ifs ----------------------------------------------------------------------------------


def test_overrides_take_the_place_of_facts_and_are_cited() -> None:
    h = _basic()
    salary = h.entities[0].id
    raise_ = Override(uuid.uuid4(), salary, "income.monthly_net", 6_000_000, ON)
    later = Override(uuid.uuid4(), salary, "income.monthly_net", 1, date(2027, 1, 1))
    run = h.run(overrides=[raise_])
    income = run.get("cashflow.monthly_income")
    assert income.value == 6_000_000
    assert income.input_override_ids == (raise_.id,)
    assert income.input_fact_ids == ()
    assert h.run(overrides=[later]).value("cashflow.monthly_income") == 5_000_000
    with pytest.raises(EngineInputError, match="what-if"):
        h.run(overrides=[Override(uuid.uuid4(), salary, "income.salary", 1, ON)])
    with pytest.raises(EngineInputError, match="two what-if"):
        h.run(overrides=[raise_, raise_])


# --- Traceability ------------------------------------------------------------------------------


def test_each_figure_cites_what_it_read() -> None:
    h = _basic()
    h.household("preference.debt_strategy", "avalanche")
    card = h.add("debt", "Card", _debt(100_000, "0.03", 10_000))
    loan = h.add("debt", "Loan", _debt(500_000, "0.01", 10_000))
    run = h.run()
    facts_of = {e: {f.id for f in h.facts if f.entity_id == e} for e in (card, loan)}
    surplus = run.get("cashflow.monthly_surplus")
    assert surplus.input_fact_ids == ()
    assert {r.key for r in surplus.input_figures} == {
        "cashflow.monthly_income", "cashflow.monthly_expenses", "cashflow.minimum_payments",
    }  # fmt: skip
    # The two are paid off together (a payment freed by either rolls to the other), so each
    # payoff reads both debts' facts; the order reads only balances, rates and the strategy.
    both = facts_of[card] | facts_of[loan]
    assert set(run.get("debt.payoff_months", card).input_fact_ids) == both
    assert set(run.get("debt.payoff_months", loan).input_fact_ids) == both
    strategy = {f.id for f in h.facts if f.attribute == "preference.debt_strategy"}
    order_reads = {f.id for f in h.facts if f.attribute in ("debt.balance", "debt.monthly_rate")}
    assert set(run.get("debt.strategy_order", card).input_fact_ids) == strategy | order_reads
    assert (
        FigureRef("debt.strategy_order", loan) in run.get("debt.payoff_months", loan).input_figures
    )
    every_fact = {f.id for f in h.facts}
    assert all(set(f.input_fact_ids) <= every_fact for f in run.figures)


# --- Arithmetic --------------------------------------------------------------------------------


def test_rounding_and_ratios() -> None:
    assert round_half_up(Decimal("2.5")) == 3
    assert round_half_up(Decimal("2.4999")) == 2
    assert interest(8_500_000, Decimal("0.03")) == 255_000
    assert interest(50, Decimal("0.01")) == 1  # 0.5 rounds up
    assert interest(49, Decimal("0.01")) == 0
    assert ratio(15_000_000, 7_000_000) == Decimal("2.142857")
    assert ratio(2, 3) == Decimal("0.666667")
    assert ceil_div(6_000_000, 505_000) == 12
    assert ceil_div(10, 5) == 2


def test_months_on_the_calendar() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 9, 15), 17) == date(2028, 2, 15)
    assert add_months(date(2026, 12, 1), 0) == date(2026, 12, 1)
    assert whole_months_until(date(2026, 9, 15), date(2027, 9, 15)) == 12
    assert whole_months_until(date(2026, 9, 15), date(2027, 9, 14)) == 11
    assert whole_months_until(date(2026, 9, 15), date(2026, 9, 1)) == 0
