"""Dreaming's checks and classification on the worked example (Phase 4, task 3).

Every claim is model output, so each refusal here is one a model could cause: a turn the session
doesn't have, a quote the household never wrote, a number that isn't in the quote (V-09), an entity
or attribute that doesn't fit. Then each fact is compared with what Kako holds: same, new, replace,
retract or conflict, and two claims of one session about the same thing are reconciled.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from kako.agents.present import Refs
from kako.dreaming.claims import (
    Claim,
    ClaimedEvent,
    ClaimedFact,
    ClaimError,
    SaidTurn,
    parse_claims,
)
from kako.dreaming.classify import Finding, Known, classify
from kako.facts.evidence import unquoted
from kako.facts.proposals import parse_fact, parse_life_event, parse_retract
from tests.support.facts import HOUSEHOLD
from tests.support.villanueva import Villanueva, build

NOV_20 = date(2026, 11, 20)
BEFORE_THE_JOB = datetime(2026, 11, 20, 11, tzinfo=UTC)  # 7 PM in Manila
NEWS = (
    "Mara here, with news: I got a new job! I start on Dec 1, and my take-home pay will be "
    "₱68,000 a month."
)
QUOTE = "I start on Dec 1, and my take-home pay will be ₱68,000 a month."
SALARY = ClaimedFact("income:mara-s-salary", "income.monthly_net", "68000", "2026-12-01")
NEW_JOB = ClaimedEvent("new_job", "Mara starts a new job", "2026-12-01")
EVENT_ID = uuid.UUID("00000000-0000-4000-8000-00000000e001")


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _known(h: Villanueva, known_at: datetime = BEFORE_THE_JOB, **extra: Any) -> Known:
    refs = Refs.of(h.entities)
    entities = {refs.by_id[e.id]: e for e in h.entities}
    return Known(HOUSEHOLD, tuple(h.facts), entities, known_at=known_at, **extra)


def _turn(text: str = NEWS, seed: str = "s4:t1", on: date = NOV_20) -> SaidTurn:
    return SaidTurn(seed, text, on, speaker="Mara")


def _claim(
    quote: str = QUOTE,
    *facts: ClaimedFact,
    event: ClaimedEvent | None = None,
    turn: str = "s4:t1",
    correction: bool = False,
) -> Claim:
    return Claim(turn, quote, correction, event, facts)


def _run(
    h: Villanueva, *claims: Claim, turns: tuple[SaidTurn, ...] = (), **known: Any
) -> list[Finding]:
    return classify(claims, turns or (_turn(),), _known(h, **known), new_id=lambda: EVENT_ID)


def _numbers_quoted(finding: Finding) -> None:
    quotes = [finding.quote, *(e.quote for e in finding.evidence)]
    for p in finding.proposals:
        assert unquoted(p.kind, p.payload, quotes, today=NOV_20) == []


def test_the_new_job_is_a_life_event_and_a_replaced_salary(house: Villanueva) -> None:
    event, salary = _run(house, _claim(QUOTE, SALARY, event=NEW_JOB))
    assert (event.outcome, salary.outcome) == ("new", "replace")
    (made,) = event.proposals
    assert made.kind == "life_event"
    assert parse_life_event(made.payload).id == EVENT_ID
    assert made.payload["source_ref"] == "s4:t1"
    (fact,) = salary.proposals
    write = parse_fact(fact.kind, fact.payload)
    old = next(
        f
        for f in house.facts
        if f.entity_id == house.ids["mara_salary"] and f.attribute == "income.monthly_net"
        and f.valid_from == date(2026, 3, 1)
    )  # fmt: skip
    assert (write.value, write.valid_from, write.replaces) == (6_800_000, date(2026, 12, 1), old.id)
    assert write.life_event_id == EVENT_ID == salary.life_event_id
    assert fact.target == f"{house.ids['mara_salary']}/income.monthly_net/2026-12-01"
    assert "₱68,000.00 from Dec 1, 2026, replacing ₱52,000.00" in salary.shown
    _numbers_quoted(event)
    _numbers_quoted(salary)


def test_a_value_kako_holds_already_is_same(house: Villanueva) -> None:
    text = "The card is at ₱76,880 now, after the November statement."
    claim = _claim(text, ClaimedFact("debt:credit-card", "debt.balance", "76880", ""), turn="s9:t1")
    (found,) = _run(house, claim, turns=(_turn(text, "s9:t1"),))
    assert found.outcome == "same"
    assert found.proposals == ()
    assert "since Nov 15, 2026" in found.reason


def test_a_new_value_for_today_replaces_the_one_in_force(house: Villanueva) -> None:
    text = "The card is at ₱75,000 now."
    claim = _claim(text, ClaimedFact("debt:credit-card", "debt.balance", "₱75,000", ""))
    (found,) = _run(house, claim, turns=(_turn(text),))
    assert found.outcome == "replace"
    write = parse_fact(found.proposals[0].kind, found.proposals[0].payload)
    assert (write.value, write.valid_from) == (7_500_000, NOV_20)  # said today, from today
    _numbers_quoted(found)


def test_a_fact_kako_has_none_of_is_new(house: Villanueva) -> None:
    text = "Mara gets paid on the 15th."
    claim = _claim(text, ClaimedFact("income:mara-s-salary", "income.pay_day", "15", ""))
    (found,) = _run(house, claim, turns=(_turn(text),))
    assert found.outcome == "new"
    assert found.proposals[0].kind == "new_fact"


def test_a_correction_retracts_and_puts_the_right_value_from_the_same_day(
    house: Villanueva,
) -> None:
    text = "Sorry, I had it wrong: rent and utilities are ₱38,000 a month, not 40,000."
    claim = _claim(
        text,
        ClaimedFact("expense:rent-and-utilities", "expense.monthly_amount", "38000", ""),
        correction=True,
    )
    (found,) = _run(house, claim, turns=(_turn(text),))
    assert found.outcome == "retract"
    retraction, corrected = found.proposals
    rent = next(
        f
        for f in house.facts
        if f.entity_id == house.ids["rent"] and f.attribute == "expense.monthly_amount"
    )
    assert retraction.kind == "retract_fact"
    assert parse_retract(retraction.payload)[0] == rent.id
    assert retraction.target == f"fact/{rent.id}"
    write = parse_fact(corrected.kind, corrected.payload)
    assert corrected.kind == "new_fact"
    assert (write.value, write.valid_from) == (3_800_000, rent.valid_from)
    (evidence,) = found.evidence
    assert evidence.fact_id == rent.id
    assert "2026-03-01" in evidence.quote
    _numbers_quoted(found)


def test_a_correction_with_no_value_retracts_only(house: Villanueva) -> None:
    text = "Jun doesn't get a 13th month pay at his job, that was a mistake."
    claim = _claim(
        text,
        ClaimedFact("income:jun-s-salary", "income.thirteenth_month", "", ""),
        correction=True,
    )
    (found,) = _run(house, claim, turns=(_turn(text),))
    assert found.outcome == "retract"
    (retraction,) = found.proposals
    assert retraction.kind == "retract_fact"
    assert parse_retract(retraction.payload)[1].startswith("Said in the session: “Jun")


def test_a_value_for_a_day_kako_has_one_for_is_a_conflict(house: Villanueva) -> None:
    text = "Rent was ₱39,000 from March 1, 2026."
    claim = _claim(
        text,
        ClaimedFact("expense:rent-and-utilities", "expense.monthly_amount", "39000", "2026-03-01"),
    )
    (found,) = _run(house, claim, turns=(_turn(text),))
    assert found.outcome == "conflict"
    assert found.proposals == ()
    assert "₱40,000.00 for the same day" in found.reason


def test_a_value_older_than_one_kako_has_is_a_conflict(house: Villanueva) -> None:
    text = "The car loan was ₱415,000 on Oct 1, 2026."
    claim = _claim(text, ClaimedFact("debt:car-loan", "debt.balance", "415000", "2026-10-01"))
    (found,) = _run(house, claim, turns=(_turn(text),))
    assert found.outcome == "conflict"
    assert "later value, from Oct 15, 2026" in found.reason


@pytest.mark.parametrize(
    ("claim", "reason"),
    [
        (_claim(QUOTE, SALARY, turn="s4:t9"), "no turn 's4:t9'"),
        (_claim("I start on Jan 1", SALARY), "the quote isn't the household's words"),
        (
            _claim("I got a new job!", SALARY),
            "not in the quote: the value ₱68,000.00; valid_from 2026-12-01",
        ),
        (
            _claim(QUOTE, ClaimedFact("income:lia-s-salary", "income.monthly_net", "68000", "")),
            "no entity 'income:lia-s-salary'",
        ),
        (
            _claim(QUOTE, ClaimedFact("debt:credit-card", "income.monthly_net", "68000", "")),
            "debt:credit-card is a debt; income.monthly_net isn't about one",
        ),
        (
            _claim(QUOTE, ClaimedFact("debt:credit-card", "plan.allocation", "68000", "")),
            "'plan.allocation' isn't an attribute dreaming can propose",
        ),
        (
            _claim(QUOTE, ClaimedFact("", "income.monthly_net", "68000", "")),
            "no entity ''",
        ),
        (
            _claim(QUOTE, ClaimedFact("income:mara-s-salary", "income.monthly_net", "lots", "")),
            "income.monthly_net: ",
        ),
        (
            _claim(
                QUOTE, ClaimedFact("income:mara-s-salary", "income.monthly_net", "68000", "Dec")
            ),
            "valid_from 'Dec' isn't a date",
        ),
        (
            _claim(QUOTE, event=ClaimedEvent("lottery", "won", "2026-12-01")),
            "'lottery' isn't a kind of life event",
        ),
    ],
)
def test_what_fails_a_check_is_refused_with_why(
    house: Villanueva, claim: Claim, reason: str
) -> None:
    (found,) = _run(house, claim)
    assert found.outcome == "refused"
    assert reason in found.reason
    assert found.proposals == ()


def test_a_life_event_kako_has_is_same_and_its_facts_name_it(house: Villanueva) -> None:
    event_id = uuid.uuid4()
    held = ((event_id, "new_job", date(2026, 12, 1)),)
    event, salary = _run(house, _claim(QUOTE, SALARY, event=NEW_JOB), life_events=held)
    assert event.outcome == "same"
    assert salary.outcome == "replace"
    assert parse_fact("replace_fact", salary.proposals[0].payload).life_event_id == event_id


def test_the_same_value_said_twice_in_a_session_is_proposed_once(house: Villanueva) -> None:
    again = "Just to say it again: ₱68,000 a month from Dec 1."
    turns = (_turn(), _turn(again, "s4:t2"))
    findings = _run(house, _claim(QUOTE, SALARY), _claim(again, SALARY, turn="s4:t2"), turns=turns)
    assert [f.outcome for f in findings] == ["replace", "same"]
    assert findings[1].reason == "said again (claim 1)"


def test_two_values_for_one_day_in_a_session_are_a_conflict(house: Villanueva) -> None:
    other = "Actually it's ₱66,000 a month from Dec 1."
    turns = (_turn(), _turn(other, "s4:t2"))
    findings = _run(
        house,
        _claim(QUOTE, SALARY),
        _claim(other, ClaimedFact(SALARY.entity, SALARY.attribute, "66000", "2026-12-01"),
               turn="s4:t2"),
        turns=turns,
    )  # fmt: skip
    assert [f.outcome for f in findings] == ["conflict", "conflict"]
    assert all(f.proposals == () or f.outcome == "conflict" for f in findings)


def test_a_second_change_waits_for_the_first(house: Villanueva) -> None:
    later = "And from Jun 1, 2027 it goes up to ₱70,000 a month."
    turns = (_turn(), _turn(later, "s4:t2"))
    findings = _run(
        house,
        _claim(QUOTE, SALARY),
        _claim(later, ClaimedFact(SALARY.entity, SALARY.attribute, "70000", "2027-06-01"),
               turn="s4:t2"),
        turns=turns,
    )  # fmt: skip
    assert [f.outcome for f in findings] == ["replace", "deferred"]


def test_once_the_job_is_known_the_news_is_all_same() -> None:
    house = build(datetime(2026, 12, 2, tzinfo=UTC))  # the story through Dec 1, the job approved
    findings = _run(house, _claim(QUOTE, SALARY), known_at=datetime(2026, 12, 2, tzinfo=UTC))
    assert [f.outcome for f in findings] == ["same"]


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({}, "claims is a list"),
        ({"claims": [1]}, "claims[1] is an object"),
        ({"claims": [{"turn": "s4:t1", "quote": "x", "facts": []}]}, "correction is true"),
        (
            {"claims": [{"turn": "s4:t1", "quote": "x", "correction": False, "facts": []}]},
            "names a life event, facts, or both",
        ),
        (
            {"claims": [{"turn": "s4:t1", "quote": "", "correction": False, "facts": [{}]}]},
            "facts[1].entity must be a string",
        ),
        ({"claims": [{"turn": 1}] * 13}, "at most 12 claims"),
    ],
)
def test_a_wrong_shape_goes_back_to_the_model(arguments: dict[str, Any], error: str) -> None:
    with pytest.raises(ClaimError, match=error.replace("[", r"\[").replace("]", r"\]")):
        parse_claims(arguments)


def test_claims_parse() -> None:
    (claim,) = parse_claims(
        {
            "claims": [
                {
                    "turn": "s4:t1",
                    "quote": f"  {QUOTE} ",
                    "correction": False,
                    "life_event": {
                        "kind": "new_job",
                        "description": "Mara starts a new job",
                        "occurs_on": "2026-12-01",
                    },
                    "facts": [
                        {
                            "entity": SALARY.entity,
                            "attribute": SALARY.attribute,
                            "value": "68000",
                            "valid_from": "2026-12-01",
                        }
                    ],
                }
            ]
        }
    )
    assert claim == Claim("s4:t1", QUOTE, False, NEW_JOB, (SALARY,))
