"""The timeline's words (`planning/timeline.py`) and what to revisit now (`decisions/revisit.py`),
on the worked example."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from kako.decisions.revisit import now_of, to_revisit
from kako.facts.model import FactRow
from kako.planning.timeline import (
    DecisionIn,
    LifeEventIn,
    PlanIn,
    SessionIn,
    Source,
    events_of,
    state_of,
    things_of,
)
from tests.support.villanueva import DEC_1, Villanueva, build

MANILA = ZoneInfo("Asia/Manila")
NOV_20 = date(2026, 11, 20)


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _salary(house: Villanueva) -> list[FactRow]:
    return sorted(
        (
            f
            for f in house.facts
            if f.entity_id == house.ids["mara_salary"] and f.attribute == "income.monthly_net"
        ),
        key=lambda f: f.valid_from,
    )


def test_each_value_has_a_state_on_the_households_date(house: Villanueva) -> None:
    old, new = _salary(house)
    assert (old.status, old.valid_to, new.valid_from) == ("replaced", DEC_1, DEC_1)
    assert (state_of(old, DEC_1), state_of(new, DEC_1)) == ("past", "current")
    # Told on Nov 20 of a job from Dec 1: the old salary still holds, the new one is coming.
    assert (state_of(old, NOV_20), state_of(new, NOV_20)) == ("current", "coming")
    wrong = replace(new, status="retracted", retracted_at=datetime(2026, 11, 21, tzinfo=UTC))
    assert state_of(wrong, DEC_1) == "corrected"


def test_each_thing_over_time(house: Villanueva) -> None:
    sources = {f.id: Source("From the household's starting figures") for f in house.facts}
    things = things_of(as_of=DEC_1, entities=house.entities, facts=house.facts, sources=sources)
    assert (things[0].name, things[0].id) == ("The household", None)
    kinds = [t.kind for t in things[1:]]
    assert kinds == sorted(kinds, key=["income", "expense", "debt", "account", "goal"].index)
    mara = next(t for t in things if t.name == "Mara's salary")
    pay = next(a for a in mara.attributes if a.attribute == "income.monthly_net")
    assert pay.words == "take-home pay a month"
    assert [(v.value, v.valid_from, v.valid_to, v.state) for v in pay.values] == [
        ("₱68,000.00", DEC_1, None, "current"),
        ("₱52,000.00", date(2026, 3, 1), DEC_1, "past"),
    ]
    card = next(t for t in things if t.name == "Credit card")
    balances = next(a for a in card.attributes if a.attribute == "debt.balance").values
    assert [v.value for v in balances] == ["₱76,880.00", "₱81,000.00", "₱85,000.00"]
    assert [v.state for v in balances] == ["current", "past", "past"]


def _events(house: Villanueva, as_of: date, **more: object) -> list:  # type: ignore[type-arg]
    job = next(f.life_event_id for f in house.facts if f.life_event_id is not None)
    assert job is not None
    sources = {
        f.id: Source(
            f"source of {f.source_kind}", approved_by=None if f.source_kind == "seed" else "Jun"
        )
        for f in house.facts
    }
    return list(
        events_of(
            as_of=as_of,
            zone=MANILA,
            entities=house.entities,
            facts=house.facts,
            sources=sources,
            life_events=[
                LifeEventIn(
                    job, "new_job", "Mara got a new job", DEC_1, "Said by Mara in Session 4", "Mara"
                )
            ],
            **more,  # type: ignore[arg-type]
        )
    )


def test_what_happened_newest_first_with_the_life_event_and_its_facts(house: Villanueva) -> None:
    events = _events(house, DEC_1)
    days = [e.on for e in events]
    assert days == sorted(days, reverse=True)
    job = next(e for e in events if e.kind == "life_event")
    assert (job.title, job.detail, job.on, job.by) == (
        "Mara got a new job",
        "New job",
        DEC_1,
        "Mara",
    )
    assert [(c.label, c.title, c.before, c.after, c.from_day) for c in job.changes] == [
        (
            "replaced",
            "Mara's salary (take-home pay a month)",
            "₱52,000.00",
            "₱68,000.00",
            "Dec 1, 2026",
        )
    ]
    # Within a day the life event comes first, and its facts aren't listed again on their own.
    assert events[0] is job
    assert not any(
        c.title == "Mara's salary (take-home pay a month)"
        for e in events
        if e.kind == "change"
        for c in e.changes
    )
    # A statement's three balances are one event.
    nov = [e for e in events if e.kind == "change" and e.on == date(2026, 11, 15)]
    assert len(nov) == 1
    assert sorted(c.title for c in nov[0].changes) == [
        "Car loan (balance)",
        "Credit card (balance)",
        "Emergency fund (balance)",
    ]
    assert {c.label for c in nov[0].changes} == {"replaced"}
    assert nov[0].by == "Jun"  # who approved the batch, from its facts' source
    allocations = [e for e in events if e.title == "The plan's amounts a month"]
    assert allocations
    assert all(c.label == "the plan's amount" for e in allocations for c in e.changes)
    start = events[-1]
    assert start.kind == "start"
    assert start.on == date(2026, 8, 1)  # the seed, recorded on the household's first day
    assert start.detail == "25 facts, the earliest true from Mar 1, 2026"
    assert start.by is None
    assert not any(e.ahead for e in events)


def test_what_is_ahead_of_the_households_date(house: Villanueva) -> None:
    events = _events(house, NOV_20)
    ahead = {e.kind for e in events if e.ahead}
    assert "life_event" in ahead
    assert all(e.on > NOV_20 for e in events if e.ahead)
    assert all(e.on <= NOV_20 for e in events if not e.ahead)


def test_decisions_plans_and_sessions_on_the_timeline(house: Villanueva) -> None:
    revisited, kept = uuid.uuid4(), uuid.uuid4()
    plan, empty, talked = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = _events(
        house,
        DEC_1,
        decisions=[
            DecisionIn(
                revisited,
                "How hard should we pay down the card?",
                "B: split",
                "Session 2",
                date(2026, 9, 15),
                "Mara",
            ),
            DecisionIn(kept, "Another?", "A", "Session 3", date(2026, 10, 18), None),
        ],
        plans=[PlanIn(plan, 1, "accepted", date(2026, 9, 15), "Session 2")],
        sessions=[
            SessionIn(empty, "Session 1", date(2026, 8, 15), 0),
            SessionIn(talked, "Session 4", NOV_20, 2),
        ],
        revisit=[revisited],
    )
    split = next(e for e in events if e.ref == revisited)
    assert (split.kind, split.detail, split.source, split.revisit) == (
        "decision",
        "Chose B: split",
        "Decided by Mara in Session 2",
        True,
    )
    assert next(e for e in events if e.ref == kept).revisit is False
    accepted = next(e for e in events if e.ref == plan)
    assert (accepted.title, accepted.detail) == ("Plan v1", "Accepted: the current plan")
    assert next(e for e in events if e.ref == talked).detail == "2 turns"
    assert not any(e.ref == empty for e in events)  # a session with no turns: its decision says it


def test_a_correction_shows_what_was_wrong_and_what_is_back(house: Villanueva) -> None:
    old, new = _salary(house)
    at = datetime(2026, 11, 21, 3, tzinfo=UTC)
    facts = [f for f in house.facts if f.id not in (old.id, new.id)]
    facts += [
        replace(old, status="active", valid_to=None, replaced_by=None),
        replace(new, status="retracted", retracted_at=at, retraction_reason="Mara misread it"),
    ]
    events = list(
        events_of(
            as_of=DEC_1,
            zone=MANILA,
            entities=house.entities,
            facts=facts,
            sources={},
        )
    )
    fixed = next(e for e in events if e.kind == "correction")
    assert fixed.on == date(2026, 11, 21)
    assert fixed.title == "Corrected: Mara's salary (take-home pay a month)"
    assert fixed.detail == "Mara misread it"
    assert [(c.label, c.before, c.after) for c in fixed.changes] == [
        ("corrected", "₱68,000.00", "₱52,000.00")
    ]


def test_what_to_revisit_now(house: Villanueva) -> None:
    old, new = _salary(house)
    by_id = {f.id: f for f in house.facts}
    jun = next(
        f
        for f in house.facts
        if f.entity_id == house.ids["jun_salary"] and f.attribute == "income.monthly_net"
    )
    decision, steady = uuid.uuid4(), uuid.uuid4()
    found = to_revisit({decision: [old.id, jun.id], steady: [jun.id]}, house.facts)
    assert list(found) == [decision]
    (change,) = found[decision]
    assert (change.label, change.old, change.new) == ("replaced", old, new)
    assert now_of(old, by_id) == new
    assert now_of(new, by_id) is None
    # A retracted fact brings back the one it replaced.
    wrong = replace(new, status="retracted")
    back = replace(old, status="active", valid_to=None, replaced_by=None)
    facts = [f for f in house.facts if f.id not in (old.id, new.id)] + [wrong, back]
    found = to_revisit({decision: [wrong.id]}, facts)
    assert [(c.label, c.new) for c in found[decision]] == [("retracted", back)]
    with pytest.raises(ValueError, match="isn't given"):
        to_revisit({decision: [uuid.uuid4()]}, house.facts)
