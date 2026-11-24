"""The reconciliation rules on the worked example (docs/architecture.md, step 6): the asks together,
over-allocation, opposite moves and a goal that misses its date, and the same rules on one split.

Sep 15 (before plan v2): surplus ₱9,050, nothing allocated yet. Dec 1 (plan v3): surplus ₱25,050,
the card ₱10,000, the emergency fund ₱10,000 and the house fund ₱5,050 a month, which reaches its
₱300,000 target on its date, Dec 1, 2031 (₱5,000 a month would do).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from kako.engine import Override, Run, compute
from kako.facts.snapshot import Snapshot, take_snapshot
from kako.planning.reconcile import Ask, check_split, combine, fits, reconcile
from tests.support.facts import HOUSEHOLD
from tests.support.villanueva import DEC_1, SEP_15, Villanueva, build

BEFORE_PLAN_V2 = datetime(2026, 9, 15, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


class World:
    def __init__(self, house: Villanueva, snap: Snapshot) -> None:
        self.house = house
        self.snap = snap
        self.base = compute(snap, house.entities)
        self.kinds = {e.id: e.kind for e in house.entities}
        self.current = {
            f.entity_id: f.value_money or 0
            for f in snap.facts
            if f.attribute == "plan.allocation" and f.entity_id is not None
        }

    def run_with(self, amounts: Mapping[uuid.UUID, int]) -> Run:
        overrides = [
            Override(uuid.uuid4(), e, "plan.allocation", c, self.snap.on)
            for e, c in amounts.items()
        ]
        return compute(self.snap, self.house.entities, overrides)

    def ask(self, specialist: str, what_if: str, **amounts: int) -> Ask:
        return Ask(specialist, what_if, tuple((self.house.ids[k], c) for k, c in amounts.items()))

    def reconcile(self, *asks: Ask):  # type: ignore[no-untyped-def]
        runs = {a.what_if: self.run_with(dict(a.allocations)) for a in asks}
        return reconcile(
            asks,
            base=self.base,
            current=self.current,
            kinds=self.kinds,
            runs=runs,
            run_with=self.run_with,
            ref="rec-W1",
        )


@pytest.fixture(scope="module")
def sep(house: Villanueva) -> World:
    return World(house, take_snapshot(HOUSEHOLD, house.facts, SEP_15, BEFORE_PLAN_V2))


@pytest.fixture(scope="module")
def dec(house: Villanueva) -> World:
    return World(house, take_snapshot(HOUSEHOLD, house.facts, DEC_1))


def test_each_entity_takes_its_own_specialists_amount(sep: World) -> None:
    card, fund = sep.house.ids["card"], sep.house.ids["fund"]
    debt = sep.ask("debt", "debt1-W1", card=905_000, fund=0)
    savings = sep.ask("savings", "savings1-W1", card=400_000, fund=505_000)
    together = combine([debt, savings], sep.kinds)
    assert {e: (c, a.what_if) for e, (c, a) in together.items()} == {
        card: (905_000, "debt1-W1"),  # the card is the debt specialist's
        fund: (505_000, "savings1-W1"),  # the fund is savings'
    }
    # Order doesn't matter for owned entities; between non-owners the last ask wins.
    assert combine([savings, debt], sep.kinds) == together
    budget_like = sep.ask("goals", "goals1-W1", fund=100_000)
    assert combine([budget_like, debt], sep.kinds)[fund] == (0, debt)


def test_the_session_2_asks_over_allocate(sep: World) -> None:
    """All ₱9,050 on the card and Jun's split, together: ₱14,100 a month against ₱9,050."""
    debt = sep.ask("debt", "debt1-W1", card=905_000, fund=0)
    savings = sep.ask("savings", "savings1-W1", card=400_000, fund=505_000)
    found = sep.reconcile(debt, savings)

    assert not fits(found.run)
    assert found.run.value("plan.unallocated") == -505_000
    [conflict] = found.conflicts
    assert conflict.kind == "over_allocation"
    assert conflict.specialists == ("debt", "savings")
    assert [(s.run, s.figure.key, s.figure.value) for s in conflict.figures] == [
        ("", "cashflow.monthly_surplus", 905_000),
        ("rec-W1", "plan.unallocated", -505_000),
    ]
    assert sorted(c for _, c, _, _ in found.allocations) == [505_000, 905_000]


def test_asks_that_fit_together_find_nothing(sep: World) -> None:
    debt = sep.ask("debt", "debt1-W1", card=400_000)
    savings = sep.ask("savings", "savings1-W1", fund=505_000)
    found = sep.reconcile(debt, savings)
    assert found.conflicts == ()
    assert found.run.value("plan.unallocated") == 0


def test_opposite_moves_on_the_emergency_fund(dec: World) -> None:
    """Plan v3 puts ₱10,000 a month in the fund. The debt specialist takes it to ₱0 for the card;
    the savings specialist raises it."""
    fund = dec.house.ids["fund"]
    assert dec.current[fund] == 1_000_000
    debt = dec.ask("debt", "debt1-W1", card=2_000_000, fund=0)
    savings = dec.ask("savings", "savings1-W1", fund=1_500_000, card=0)
    found = dec.reconcile(debt, savings)

    kinds = [c.kind for c in found.conflicts]
    assert "opposite_moves" in kinds
    moves = [c for c in found.conflicts if c.kind == "opposite_moves"]
    by_entity = {c.entity_id: c for c in moves}
    assert set(by_entity) == {dec.house.ids["card"], fund}  # both are pulled two ways
    on_fund = by_entity[fund]
    assert on_fund.specialists == ("debt", "savings")
    assert on_fund.current == 1_000_000
    assert [(m.what_if, m.centavos) for m in on_fund.moves] == [
        ("debt1-W1", 0),
        ("savings1-W1", 1_500_000),
    ]
    assert {s.run for s in on_fund.figures} == {"debt1-W1", "savings1-W1"}
    assert {s.figure.key for s in on_fund.figures} == {"savings.months_to_target"}


def test_one_specialist_changing_its_mind_is_no_opposite_move(dec: World) -> None:
    first = dec.ask("debt", "debt1-W1", card=2_000_000)
    second = dec.ask("debt", "debt2-W1", card=500_000)
    found = dec.reconcile(first, second)
    assert [c.kind for c in found.conflicts] == []


def test_a_goal_on_track_that_slips_is_a_missed_target(dec: World) -> None:
    house_fund = dec.house.ids["house"]
    assert dec.base.value("goal.on_track", house_fund) == 1
    # The debt specialist moves the house fund's ₱5,050 to the card; the goals specialist keeps
    # it. The goals specialist owns the house fund, so it keeps ₱5,050 together: on track, but
    # together the asks are over the surplus.
    debt = dec.ask("debt", "debt1-W1", card=1_505_000, house=0)
    goals = dec.ask("goals", "goals1-W1", house=505_000)
    found = dec.reconcile(debt, goals)
    assert [c.kind for c in found.conflicts] == ["over_allocation"]

    # Only the savings specialist names the house fund, and takes its ₱5,050: off track.
    savings = dec.ask("savings", "savings1-W1", fund=1_505_000, house=0)
    found = dec.reconcile(savings)
    [missed] = [c for c in found.conflicts if c.kind == "target_missed"]
    assert missed.entity_id == house_fund
    assert [(s.run, s.figure.key) for s in missed.figures] == [
        ("rec-W1", "goal.on_track"),
        ("rec-W1", "goal.projected_date"),
        ("rec-W1", "goal.required_monthly"),
    ]
    assert missed.figures[0].figure.value == 0


def test_a_goal_raised_but_still_short_is_a_missed_target(dec: World) -> None:
    """A split that raises the house fund from nothing to ₱4,999, below the ₱5,000 a month its
    date needs: still off track."""
    house_fund = dec.house.ids["house"]
    run = dec.run_with({house_fund: 499_900})
    found = check_split(
        run,
        ref="orch-W1",
        allocations={house_fund: 499_900},
        base=dec.base,
        current={**dec.current, house_fund: 0},  # as if nothing were allocated to it yet
        kinds=dec.kinds,
    )
    assert [c.kind for c in found] == ["target_missed"]


def test_a_split_is_checked_by_the_same_rules(sep: World) -> None:
    card, fund = sep.house.ids["card"], sep.house.ids["fund"]
    over = {card: 400_000, fund: 905_000}
    found = check_split(
        sep.run_with(over),
        ref="orch-W1",
        allocations=over,
        base=sep.base,
        current=sep.current,
        kinds=sep.kinds,
    )
    assert [c.kind for c in found] == ["over_allocation"]
    assert found[0].figures[1].figure.value == -400_000

    split = {card: 400_000, fund: 505_000}
    assert (
        check_split(
            sep.run_with(split),
            ref="orch-W2",
            allocations=split,
            base=sep.base,
            current=sep.current,
            kinds=sep.kinds,
        )
        == ()
    )
