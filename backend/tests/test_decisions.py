"""What a decision rests on (`decisions.assumptions`): the ground under it, not the plan working."""

from __future__ import annotations

from kako.decisions.assumptions import PROGRESS, assumptions
from kako.facts.snapshot import take_snapshot
from tests.support.facts import HOUSEHOLD
from tests.support.villanueva import SEP_15, build


def test_plan_v2_rests_on_the_income_the_costs_and_the_preferences() -> None:
    house = build()
    snap = take_snapshot(HOUSEHOLD, house.facts, SEP_15, None)
    rests_on = set(assumptions(snap))
    by_id = {f.id: f for f in snap.facts}
    attributes = {by_id[i].attribute for i in rests_on}
    assert "income.monthly_net" in attributes
    assert "debt.monthly_rate" in attributes
    assert "expense.monthly_amount" in attributes
    assert not attributes & PROGRESS  # balances, savings and allocations move as the plan works
    assert rests_on == {f.id for f in snap.facts if f.attribute not in PROGRESS}
    assert list(assumptions(snap)) == sorted(rests_on, key=str)  # a stable order
