"""The number check (V-10) on the worked example's session 2: what it reads out of a text, what each
number matches, and what fails. No model: the texts are written here."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kako.agents.brief import EarlierTurn
from kako.agents.numbers import check_text, check_texts, mismatch, names_of, pool_of
from kako.agents.tools import MESSAGE_CHARS, TurnState
from tests.support.villanueva import Villanueva, build
from tests.test_agents_turn import ALL_ON_CARD, SPLIT, _state


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


@pytest.fixture
def state(house: Villanueva) -> TurnState:
    s = _state(house)
    s.what_if("debt1", s.allocations(ALL_ON_CARD, "debt#1"))  # debt1-W1: all on the card
    s.what_if("savings1", s.allocations(SPLIT, "savings#1"))  # savings1-W1: Jun's split
    return s


def _matches(state: TurnState, text: str) -> list[tuple[str, str, str | None]]:
    check = check_text("reply", "the reply", text, pool_of(state), names_of(state))
    return [(n.text, n.kind, n.match) for n in check.numbers]


def test_figures_facts_allocations_and_the_households_words_match(state: TurnState) -> None:
    text = (
        "The surplus is ₱9,050.00. All of it on the card pays it off in 9 months with ₱12,460.10 "
        "of interest; Jun's ₱4,000 with the rest (₱5,050.00) to the fund takes 17 months and "
        "reaches the 3-month target in 12 months. The runway is 2.1 months. The card charges 3% a "
        "month. Savings would be 5.1% of income. Paid off Feb 15, 2028."
    )
    assert _matches(state, text) == [
        ("₱9,050.00", "money", "figure:cashflow.monthly_surplus"),
        ("9 months", "months", "figure:debt1-W1:debt.payoff_months@debt:credit-card"),
        ("₱12,460.10", "money", "figure:debt1-W1:debt.total_interest@debt:credit-card"),
        ("₱4,000", "money", "allocation:savings1-W1:debt:credit-card"),
        ("₱5,050.00", "money", "allocation:savings1-W1:account:emergency-fund"),
        ("17 months", "months", "figure:savings1-W1:debt.payoff_months@debt:credit-card"),
        ("3-month", "months", "fact:household.emergency_months_target"),
        ("12 months", "months", "figure:savings1-W1:savings.months_to_target"),
        ("2.1 months", "months", "figure:savings.emergency_runway_months"),
        ("3%", "percent", "fact:debt:credit-card/debt.monthly_rate"),
        ("5.1%", "percent", "figure:savings1-W1:cashflow.savings_rate"),
        ("Feb 15, 2028", "date", "figure:savings1-W1:debt.payoff_date@debt:credit-card"),
    ]


def test_a_number_at_a_lower_precision_is_the_figure_rounded(state: TurnState) -> None:
    assert [m for _, _, m in _matches(state, "₱12,460 of interest by Feb 2028, in 2028")] == [
        "figure:debt1-W1:debt.total_interest@debt:credit-card",
        "figure:savings1-W1:debt.payoff_date@debt:credit-card",
        "figure:debt1-W1:debt.payoff_date@debt:car-loan",  # a year: any date in it
    ]


def test_a_shortfall_matches_the_negative_figure(state: TurnState) -> None:
    both = state.allocations(
        [
            {"entity": "debt:credit-card", "amount": "figure:cashflow.monthly_surplus"},
            {"entity": "account:emergency-fund", "amount": "said:4000"},
        ]
    )
    state.what_if("rec", both)  # ₱4,000 over the surplus
    assert _matches(state, "Together they ask ₱4,000.00 more than the surplus.") == [
        ("₱4,000.00", "money", "figure:rec-W1:plan.unallocated"),
    ]
    assert state.what_ifs["rec-W1"].run.value("plan.unallocated") == -400_000


def test_numbers_worked_out_by_a_model_fail(state: TurnState) -> None:
    text = (
        "A is 8 months faster and saves ₱11,843.52 in interest, about ₱12,000. "
        "Roughly 150k over a year."
    )
    found = _matches(state, text)
    assert [(t, k) for t, k, m in found if m is None] == [
        ("8 months", "months"),
        ("₱11,843.52", "money"),
        ("₱12,000", "money"),
        ("150k", "scaled"),
    ]


def test_refs_never_pass(state: TurnState) -> None:
    found = _matches(state, "See debt1-W1 and figure:savings1-W1:savings.months_to_target.")
    assert [(t, k, m) for t, k, m in found] == [  # one code a word, however many digits
        ("debt1-W1", "code", None),
        ("figure:savings1-W1:savings.months_to_target", "code", None),
    ]
    told = mismatch(check_texts(state, [("reply", "the reply", "See debt1-W1.")]))
    assert "'debt1-W1' in the reply." in told  # named once
    assert "refs or codes" in told
    assert "match no figure" not in told  # no number to take out, only the ref


def test_a_specialists_summary_may_name_refs_of_this_turn(state: TurnState) -> None:
    text = "All on the card (debt1-W1): figure:debt1-W1:debt.payoff_months@debt:credit-card, W9x2."
    [check] = check_texts(state, [("recommendation", "the summary", text)], refs_allowed=True)
    assert [(n.text, n.match) for n in check.numbers] == [
        ("debt1-W1", "ref"),
        ("figure:debt1-W1:debt.payoff_months@debt:credit-card", "ref"),
        ("W9x2", None),  # a code, not a ref of this turn
    ]
    assert not check.ok
    [household] = check_texts(state, [("reply", "the reply", text)])
    assert all(n.match is None for n in household.numbers)  # the household's texts: no refs


def test_names_terms_and_ordinals(state: TurnState, house: Villanueva) -> None:
    # 13th-month pay is a name, not a number; an ordinal is a number like any other.
    assert _matches(state, "Your 13th-month pay comes in December.") == []
    assert _matches(state, "The card is 1st in the payoff order.") == [
        ("1", "number", "figure:debt.strategy_order@debt:credit-card"),
    ]


def test_spelled_out_numbers_with_a_unit_are_checked(state: TurnState) -> None:
    assert _matches(state, "Two ways to go: clear the card, or keep cash for school.") == []
    assert _matches(
        state, "Nine months on the card, or seventeen months; eight months sooner."
    ) == [
        ("Nine months", "months", "figure:debt1-W1:debt.payoff_months@debt:credit-card"),
        ("seventeen months", "months", "figure:savings1-W1:debt.payoff_months@debt:credit-card"),
        ("eight months", "months", None),
    ]
    assert [
        m for _, _, m in _matches(state, "about one year, or 1 year, or forty-two percent")
    ] == [
        "figure:savings1-W1:savings.months_to_target",  # 12 months
        "figure:savings1-W1:savings.months_to_target",
        None,
    ]


def test_a_number_with_a_multiplier_never_matches(house: Villanueva) -> None:
    s = _state(house, "We have 2 kids and 12 goals.")
    assert _matches(s, "Save ₱2M a year, about 12 thousand pesos, or 9k.") == [
        ("₱2M", "scaled", None),
        ("12 thousand", "scaled", None),
        ("9k", "scaled", None),
    ]
    # The household's small numbers are counts, never pesos: "2 kids" is not ₱2.
    assert _matches(s, "₱2 a month")[0] == ("₱2", "money", None)


def test_dates_in_any_common_form_are_one_date(state: TurnState) -> None:
    payoff = "figure:savings1-W1:debt.payoff_date@debt:credit-card"  # Feb 15, 2028
    for written in (
        "Feb 15, 2028",
        "February 15th, 2028",
        "15 Feb 2028",
        "the 15th of February 2028",
        "2028-02-15",
        "15/02/2028",
        "02/15/2028",
        "Feb 15",
    ):
        assert _matches(state, f"Paid off {written}.") == [(written, "date", payoff)], written
    for wrong in (
        "March 3rd, 2028",
        "3 March 2028",
        "2028-03-03",
        "03/03/2028",
        "Feb 30, 2028",
        "March 3",
    ):
        [(text, kind, match)] = _matches(state, f"Paid off {wrong}.")
        assert (text, kind, match) == (wrong, "date", None), wrong


def test_refs_in_a_summary_must_be_the_turns_own(state: TurnState) -> None:
    text = "See figure:50000php and fact:x-99999k, not debt1-W1."
    [check] = check_texts(state, [("recommendation", "the summary", text)], refs_allowed=True)
    assert [(n.text, n.match) for n in check.numbers] == [
        ("figure:50000php", None),
        ("99999k", None),
        ("debt1-W1", "ref"),
    ]


def test_odd_numbers_fail_without_crashing(state: TurnState, house: Villanueva) -> None:
    assert _matches(state, "₱9,050.0000000000000000000000001 and 1" + "0" * 40) == [
        ("₱9,050.0000000000000000000000001", "money", None),
        ("1" + "0" * 40, "number", None),
    ]
    # A name with a digit is left out only as a whole word: "Card 15,000" keeps its 15,000.
    pool = pool_of(state)
    check = check_text("reply", "the reply", "Card 15,000 and Card 1.", pool, ("Card 1",))
    assert [n.text for n in check.numbers] == ["15,000"]
    # Numbers past what the agents were shown of the message are not the household's.
    long = _state(house, "x" * MESSAGE_CHARS + " 777 pesos")
    assert _matches(long, "₱777") == [("₱777", "money", None)]


def test_the_households_own_numbers_match(house: Villanueva) -> None:
    s = _state(house, "Can we do 4000 a month on the card from March 2027?")
    assert _matches(s, "₱4,000.00 a month from March 2027") == [
        ("₱4,000.00", "money", "said"),
        ("March 2027", "month", "said"),
    ]


def test_the_mismatch_names_each_number_and_where(state: TurnState) -> None:
    checks = check_texts(
        state,
        [
            ("reply", "the reply", "A is 8 months faster."),
            ("recommendation", "option 'A: card'", "Saves ₱11,843.52."),
            ("recommendation", "option 'B: split'", "Takes 17 months."),
        ],
    )
    assert [c.ok for c in checks] == [False, False, True]
    assert [c.result for c in checks] == ["fail", "fail", "pass"]
    told = mismatch(checks)
    assert "'8 months' in the reply; '₱11,843.52' in option 'A: card'." in told
    assert "never work one out" in told


def test_the_households_earlier_words_in_the_session_match(house: Villanueva) -> None:
    """Pim's sandbox, Nov 25: "what if my salary goes to 200000 per month", then "Jun". The
    reply to "Jun" may quote the amount back: the household said it, in this session."""
    s = _state(house, message="Jun")
    earlier = (EarlierTurn("Jun", "what if my salary goes to 200000 per month", "Whose?"),)
    s.inputs = replace(s.inputs, earlier=earlier)
    text = "Jun's salary at ₱200,000.00 a month is a change Kako can't test yet."
    assert _matches(s, text) == [("₱200,000.00", "money", "said")]
    # Kako's own earlier replies are not the household's words: their numbers match nothing.
    s.inputs = replace(
        s.inputs, earlier=(EarlierTurn("Jun", "Jun", "It lasts ₱123,456.00 longer."),)
    )
    assert _matches(s, "₱123,456.00")[0][2] is None
