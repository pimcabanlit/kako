"""Patterns, promotion payloads and decision records (Phase 4, task 4), in memory.

A pattern is three choices the same way across at least two sessions, with none the other way, that
the household doesn't already hold. A promotion names what it shares by id only. A decision record
is written by code from the decision's rows, and the same decision always gives the same record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from kako.dreaming.patterns import Choice, find_patterns
from kako.facts.evidence import payload_numbers
from kako.facts.model import EntityRow, FactRow
from kako.facts.proposals import PayloadError, parse_promote, promote_payload
from kako.meko.fake import FakeMeko
from kako.upkeep.records import DecisionRecord, OptionRecord, Revised, decision_record

S1, S2, S3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
FLEX = frozenset({"favours_flexibility"})
SPEED = frozenset({"favours_speed"})


def choice(session: uuid.UUID, title: str, on: date, tags: frozenset[str]) -> Choice:
    return Choice(uuid.uuid4(), session, title, on, None, "We want cash on hand.", tags)


AUG = choice(S1, "Session 1", date(2026, 8, 15), FLEX)
SEP = choice(S2, "Session 2", date(2026, 9, 15), FLEX)
OCT = choice(S3, "Session 3", date(2026, 10, 18), FLEX)


def test_three_choices_across_sessions_make_a_pattern_citing_each() -> None:
    (pattern,) = find_patterns([OCT, AUG, SEP], {})
    assert (pattern.attribute, pattern.value) == ("preference.debt_vs_flexibility", "flexibility")
    assert pattern.choices == (AUG, SEP, OCT)  # oldest first
    assert pattern.explanation == (
        "In its decisions in Session 1, Session 2 and Session 3, the household kept cash on hand "
        "rather than paying debt off faster, and it never chose the other way."
    )


def test_what_isnt_a_pattern() -> None:
    assert find_patterns([AUG, SEP], {}) == []  # two choices
    same_session = [choice(S1, "Session 1", date(2026, 8, 15), FLEX) for _ in range(3)]
    assert find_patterns(same_session, {}) == []  # one session
    other_way = choice(S3, "Session 3", date(2026, 10, 19), SPEED)
    assert find_patterns([AUG, SEP, OCT, other_way], {}) == []  # one choice the other way
    held = {"preference.debt_vs_flexibility": "flexibility"}
    assert find_patterns([AUG, SEP, OCT], held) == []  # the household holds it already
    untagged = choice(S3, "Session 3", date(2026, 10, 18), frozenset())
    assert find_patterns([AUG, SEP, untagged], {}) == []


def test_a_pattern_against_what_the_household_holds_is_proposed() -> None:
    (pattern,) = find_patterns([AUG, SEP, OCT], {"preference.debt_vs_flexibility": "balanced"})
    assert pattern.value == "flexibility"
    speed = [
        choice(S1, "Session 1", AUG.session_on, SPEED),
        choice(S2, "Session 2", SEP.session_on, SPEED),
        choice(S2, "Session 2", SEP.session_on, SPEED),
    ]
    (fast,) = find_patterns(speed, {})
    assert fast.value == "speed"
    assert "paid debt off faster rather than keeping cash on hand" in fast.explanation


def test_a_promotion_names_what_it_shares_by_id_only() -> None:
    fact_id, decision_id = uuid.uuid4(), uuid.uuid4()
    assert promote_payload("fact", fact_id) == {"fact_id": str(fact_id)}
    assert parse_promote(promote_payload("decision", decision_id)) == ("decision", decision_id)
    assert payload_numbers("promote", promote_payload("fact", fact_id)) == []
    with pytest.raises(PayloadError):
        promote_payload("plan", fact_id)
    for bad in (
        {},
        {"fact_id": str(fact_id), "decision_id": str(decision_id)},
        {"plan_id": str(fact_id)},
        {"fact_id": "not an id"},
        {"_id": str(fact_id)},
        ["fact_id"],
    ):
        with pytest.raises(PayloadError):
            parse_promote(bad)


def _fact(attribute: str, money: int | None, text: str | None, entity: uuid.UUID | None) -> FactRow:
    return FactRow(
        id=uuid.uuid4(),
        household_id=uuid.uuid4(),
        entity_id=entity,
        attribute=attribute,
        value_money=money,
        value_rate=None,
        value_int=None,
        value_date=None,
        value_text=text,
        valid_from=date(2026, 3, 1),
        valid_to=date(2026, 12, 1),  # replaced since: the record says what it rested on then
        replaces=None,
        replaced_by=None,
        status="replaced",
        recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
        retracted_at=None,
        retraction_reason=None,
        source_kind="seed",
        source_ref="facts.csv",
        proposal_id=None,
        life_event_id=None,
    )


def test_a_decision_record_names_the_choice_what_was_turned_down_and_what_it_rests_on() -> None:
    salary = EntityRow(uuid.uuid4(), uuid.uuid4(), "income", "Mara's salary", None, None)
    rests_on = (
        _fact("income.monthly_net", 5_200_000, None, salary.id),
        _fact("preference.debt_strategy", None, "avalanche", None),
    )
    record = DecisionRecord(
        id=uuid.uuid4(),
        question="How hard should we pay down the credit card?",
        chosen="B: split",
        reasoning="Lia starts school and\n# we want cash on hand.",
        valid_from=date(2026, 9, 15),
        session_title="Session 2",
        approved_by="Mara",
        approved_on=date(2026, 9, 15),
        options=(
            OptionRecord("B: split", True, None),
            OptionRecord("A: all extra on the card", False, "We want cash on hand."),
            OptionRecord("C: minimum only", False, None),
        ),
        rests_on=rests_on,
        revises=Revised("Should we keep a buffer?", "Yes", "Session 1"),
    )
    text = decision_record("Villanueva household", record, {salary.id: salary})
    assert text == decision_record("Villanueva household", record, {salary.id: salary})
    assert text.splitlines()[0] == "# Decision record: How hard should we pay down the credit card?"
    assert "The Villanueva household decided this in Session 2, in force from Sep 15, 2026." in text
    assert "Mara approved it on Sep 15, 2026." in text
    # The household's words stay on one line: they can't start a heading of their own.
    assert "B: split. Why, in the household's words: \"Lia starts school and # we want" in text
    assert "\n# we want" not in text
    assert "- A: all extra on the card: We want cash on hand." in text
    assert "- C: minimum only: no reason was recorded" in text
    assert "- Mara's salary (take-home pay a month): ₱52,000.00, from Mar 1, 2026" in text
    assert "- The household's debt payoff strategy: avalanche, from Mar 1, 2026" in text
    assert (
        "It replaces the decision made in Session 1: Should we keep a buffer? (chosen then: Yes)."
        in text
    )
    assert "B: split:" not in text  # the chosen option isn't turned down


async def test_the_fake_promotes_once_and_lists_what_it_promoted() -> None:
    meko = FakeMeko()
    conversation = await meko.create_conversation(agent_id="kako:upkeep", title="t")
    memory_id = await meko.add_memory(
        conversation, "We keep cash on hand.", {}, agent_id="kako:upkeep"
    )
    assert await meko.promote_memories(
        conversation, [memory_id, "nope"], agent_id="kako:upkeep"
    ) == (memory_id,)
    assert await meko.promote_memories(conversation, [memory_id], agent_id="kako:upkeep") == ()
    assert await meko.get_memory(conversation, memory_id, agent_id="kako:upkeep") is None
    listed = await meko.promoted_memories(conversation, agent_id="kako:upkeep")
    assert [(m.id, m.text, m.agent_id) for m in listed.memories] == [
        (memory_id, "We keep cash on hand.", "kako:upkeep")
    ]
    assert listed.complete
    hits = await meko.search_knowledge(conversation, "cash on hand", agent_id="kako:upkeep")
    assert [h.text for h in hits] == ["We keep cash on hand."]
