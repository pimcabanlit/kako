"""Before and after an option (docs/data-model.md, "Before and after an option", C-1 to C-3), on the
worked example: session 2's options A and B beside today's plan as the turn read it (Sep 15, 2026,
known at 09:00 Manila: the minimums only), every number to the centavo, and the words the screens
show. Then each kind of change on its own, a worse option and an unchanged one against plan v2.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from kako.engine.compare import NEVER, Change, Outcome, change, outcome_pairs
from kako.engine.inputs import Override
from kako.facts.snapshot import take_snapshot
from kako.planning.compare import Comparison, comparison
from tests.support.facts import HOUSEHOLD
from tests.support.villanueva import DEC_1, SEP_15, Villanueva, build

TURN_READ = datetime(2026, 9, 15, 1, tzinfo=UTC)  # session 2's turn, 09:00 Manila
PLAN_V2 = datetime(2026, 9, 15, 18, tzinfo=UTC)  # after the household chose option B


def _ov(h: Villanueva, key: str, centavos: int) -> Override:
    return Override(uuid.uuid4(), h.ids[key], "plan.allocation", centavos, SEP_15)


def _compare(
    h: Villanueva, known_at: datetime, options: Sequence[tuple[str, Sequence[Override]]]
) -> Comparison:
    snapshot = take_snapshot(HOUSEHOLD, h.facts, SEP_15, known_at)
    return comparison(uuid.uuid4(), snapshot, h.entities, options)


@pytest.fixture(scope="module")
def session_2() -> Comparison:
    h = build(through=TURN_READ)
    return _compare(
        h,
        TURN_READ,
        [
            ("A: all extra on the card", [_ov(h, "card", 905_000)]),
            ("B: split it", [_ov(h, "card", 400_000), _ov(h, "fund", 505_000)]),
        ],
    )


def _rows(c: Comparison) -> dict[str, tuple[str, list[tuple[str, str | None, str]]]]:
    return {
        r.label: (r.before.value, [(o.value, o.change, o.direction) for o in r.options])
        for r in c.rows
    }


def test_session_2_today_and_each_option_in_words(session_2: Comparison) -> None:
    assert session_2.as_of == SEP_15
    assert session_2.baseline == (
        "Today's plan on Sep 15, 2026: the minimums only, with ₱9,050.00 a month not yet planned."
    )
    assert session_2.each_month == "the minimums only"
    assert [(o.label, o.each_month) for o in session_2.options] == [
        ("A: all extra on the card", "₱9,050.00 a month to the Credit card"),
        (
            "B: split it",
            "₱4,000.00 a month to the Credit card and ₱5,050.00 a month to the Emergency fund",
        ),
    ]


def test_session_2_what_each_reaches_and_what_it_changes(session_2: Comparison) -> None:
    assert _rows(session_2) == {
        "Credit card paid off": (
            "Aug 15, 2030",
            [
                ("Jun 15, 2027", "38 months sooner", "better"),
                ("Feb 15, 2028", "30 months sooner", "better"),
            ],
        ),
        "Credit card interest": (
            "₱111,635.47",
            [
                ("₱12,460.10", "₱99,175.37 less", "better"),
                ("₱24,303.62", "₱87,331.85 less", "better"),
            ],
        ),
        "Car loan paid off": (
            "Jan 15, 2030",
            [
                ("Sep 15, 2028", "16 months sooner", "better"),
                ("May 15, 2029", "8 months sooner", "better"),
            ],
        ),
        "Car loan interest": (
            "₱66,370.04",
            [
                ("₱45,917.97", "₱20,452.07 less", "better"),
                ("₱58,333.22", "₱8,036.82 less", "better"),
            ],
        ),
        "Interest on every debt": (
            "₱178,005.51",
            [
                ("₱58,378.07", "₱119,627.44 less", "better"),
                ("₱82,636.84", "₱95,368.67 less", "better"),
            ],
        ),
        "Emergency fund at its target": (
            "never",
            [("never", "no change", "same"), ("Sep 15, 2027", "reached in 12 months", "better")],
        ),
        "Left unplanned a month": ("₱9,050.00", [("₱0.00", None, "none"), ("₱0.00", None, "none")]),
    }
    notes = {r.label: (r.before.note, [o.note for o in r.options]) for r in session_2.rows}
    assert notes["Credit card paid off"] == ("in 47 months", ["in 9 months", "in 17 months"])
    assert notes["Emergency fund at its target"] == (
        "nothing allocated to it",
        ["nothing allocated to it", "in 12 months"],
    )


def test_the_cards_show_the_dates_and_the_interest_in_all(session_2: Comparison) -> None:
    assert [r.label for r in session_2.rows if r.on_card] == [
        "Credit card paid off",
        "Car loan paid off",
        "Interest on every debt",
        "Emergency fund at its target",
    ]
    keys = [r.key for r in session_2.rows]
    assert len(set(keys)) == len(keys)
    assert "interest_total" in keys
    assert "unplanned" in keys


def test_option_a_month_by_month_beside_today(session_2: Comparison) -> None:
    a = session_2.months[0]
    assert a.label == "A: all extra on the card"
    card, car = a.debts
    assert (card.name, card.paid_off, len(card.rows)) == ("Credit card", date(2027, 6, 15), 9)
    assert card.closing == "Paid off Jun 15, 2027: ₱97,460.10 paid, ₱12,460.10 of it interest."
    assert card.before_closing == (
        "Today's plan would still owe ₱85,000.00 then, and pay it off Aug 15, 2030 with "
        "₱111,635.47 interest."
    )
    assert (card.change, card.direction) == ("38 months sooner than today's plan", "better")
    assert (card.paid_total, card.interest_total, card.principal_total) == (
        "₱97,460.10",
        "₱12,460.10",
        "₱85,000.00",
    )
    first = card.rows[0]
    assert (first.month, first.on, first.payment, first.interest) == (
        1,
        date(2026, 10, 15),
        "₱11,600.00",
        "₱2,550.00",
    )
    # Today's plan pays only the minimum, which is the month's interest: the balance stays put.
    assert {r.before_left for r in card.rows} == {"₱85,000.00"}
    assert all(r.before_fill == 1.0 for r in card.rows)
    assert card.rows[-1].left == "₱0.00"
    assert card.rows[-1].fill == 0.0
    assert all(r.rolled_in is None for r in card.rows)
    # The card's whole payment rolls into the car loan the month after it is paid off.
    rolled = [(r.on, r.rolled_in, r.rolled_from) for r in car.rows if r.rolled_in]
    assert rolled == [(date(2027, 7, 15), "₱11,600.00", "Credit card")]
    assert car.before_closing == (
        "Today's plan would still owe ₱177,756.65 then, and pay it off Jan 15, 2030 with "
        "₱66,370.04 interest."
    )
    assert a.fund is None  # nothing goes into the emergency fund with A


def test_option_b_the_emergency_fund_climbs_to_its_target(session_2: Comparison) -> None:
    b = session_2.months[1]
    card, car = b.debts
    assert card.paid_off == date(2028, 2, 15)
    rolled = [(r.on, r.rolled_in, r.rolled_from) for r in car.rows if r.rolled_in]
    assert rolled == [(date(2028, 3, 15), "₱6,550.00", "Credit card")]
    assert car.before_closing is not None
    assert "₱86,862.83" in car.before_closing
    fund = b.fund
    assert fund is not None
    assert (fund.name, fund.target, fund.reached_on) == (
        "Emergency fund",
        "₱210,000.00",
        date(2027, 9, 15),
    )
    assert fund.closing == "At its ₱210,000.00 target on Sep 15, 2027, in 12 months."
    assert fund.before_closing == "Today's plan never gets there: nothing is set aside for it."
    assert len(fund.rows) == 12
    first, last = fund.rows[0], fund.rows[-1]
    assert (first.added, first.balance, first.to_go) == ("₱5,050.00", "₱155,050.00", "₱54,950.00")
    assert (last.on, last.balance, last.to_go, last.fill) == (
        date(2027, 9, 15),
        "₱210,600.00",
        None,
        1.0,
    )
    assert [r.month for r in fund.rows] == list(range(1, 13))


def test_a_worse_option_and_an_unchanged_one_against_plan_v2() -> None:
    h = build(through=PLAN_V2)
    c = _compare(
        h,
        PLAN_V2,
        [("Nothing extra", [_ov(h, "card", 0), _ov(h, "fund", 0)]), ("As it is", [])],
    )
    assert c.baseline == (
        "Today's plan on Sep 15, 2026: ₱4,000.00 a month to the Credit card and ₱5,050.00 a "
        "month to the Emergency fund."
    )
    assert c.each_month == (
        "₱4,000.00 a month to the Credit card and ₱5,050.00 a month to the Emergency fund"
    )
    assert c.options[0].each_month == "nothing to the Credit card and nothing to the Emergency fund"
    assert c.options[1].each_month == "nothing more set aside"
    rows = _rows(c)
    assert rows["Credit card paid off"][1][0] == ("Aug 15, 2030", "30 months later", "worse")
    assert rows["Interest on every debt"][1][0] == ("₱178,005.51", "₱95,368.67 more", "worse")
    assert rows["Emergency fund at its target"][1][0] == ("never", "never reached", "worse")
    assert all(cells[1][1:] == ("no change", "same") for label, (_, cells) in rows.items()
               if label != "Left unplanned a month")  # fmt: skip
    worse, same = c.months
    assert worse.debts[0].change == "30 months later than today's plan"
    assert worse.debts[0].direction == "worse"
    assert worse.debts[0].before_closing == (
        "Today's plan pays it off sooner: Feb 15, 2028 with ₱24,303.62 interest."
    )
    assert worse.fund is None
    assert same.debts[0].change == "the same month as today's plan"
    assert same.debts[0].direction == "same"
    assert same.fund is not None
    assert same.fund.before_closing == "Today's plan gets there Sep 15, 2027, in 12 months."


def _time(months: int | None, flag: str | None = None) -> Outcome:
    return Outcome("debt_paid", None, "Card", months, None, None, flag)


def _money(amount: int | None, kind: str = "interest_total") -> Outcome:
    return Outcome(kind, None, "", None, None, amount, None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (_time(10), _time(4), Change("sooner", "better", 6, None)),
        (_time(4), _time(10), Change("later", "worse", 6, None)),
        (_time(4), _time(4), Change("same", "same", 0, None)),
        (_time(None, "never_pays_off"), _time(7), Change("reached", "better", 7, None)),
        (_time(7), _time(None, "never_pays_off"), Change("never", "worse", None, None)),
        (_time(None, "no_allocation"), _time(None, "never_pays_off"),
         Change("same", "same", None, None)),
        (_time(None, "missing_fact"), _time(7), Change("none", "none", None, None)),
        (_time(7), _time(None, "missing_fact"), Change("none", "none", None, None)),
        (_money(500), _money(200), Change("less", "better", None, 300)),
        (_money(200), _money(500), Change("more", "worse", None, 300)),
        (_money(200), _money(200), Change("same", "same", None, 0)),
        (_money(None), _money(200), Change("none", "none", None, None)),
        (_money(0, "unplanned"), _money(905_000, "unplanned"),
         Change("none", "none", None, 905_000)),
    ],
)  # fmt: skip
def test_each_kind_of_change(before: Outcome, after: Outcome, expected: Change) -> None:
    assert change(before, after) == expected


def test_only_the_same_outcome_is_compared() -> None:
    with pytest.raises(ValueError, match="same outcome"):
        change(_time(4), _money(4))
    assert {"never_pays_off", "no_allocation"} == NEVER
    other = Outcome("debt_paid", uuid.uuid4(), "Card", 4, None, None, None)
    assert outcome_pairs([_time(10)], [other]) == ()


def test_a_goal_no_run_can_tell_stays_in_the_table_but_off_the_cards() -> None:
    h = build()
    # The house fund without what it holds: no run can say when it gets there.
    facts = [
        f for f in h.facts if (f.entity_id, f.attribute) != (h.ids["house"], "goal.saved_amount")
    ]
    snapshot = take_snapshot(HOUSEHOLD, facts, DEC_1)
    c = comparison(uuid.uuid4(), snapshot, h.entities, [("As it is", [])])
    house = next(r for r in c.rows if r.label == "House fund reached")
    assert house.before.value == "unknown"
    assert house.before.note == "a fact it needs is missing"
    assert [o.value for o in house.options] == ["unknown"]
    assert house.on_card is False
    assert next(r for r in c.rows if r.label == "Emergency fund at its target").on_card is True
