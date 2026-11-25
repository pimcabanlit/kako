"""`propose_change` on the worked example: the household's words in, checked pending proposals out.

Every argument is model output, so each refusal here is one a model could make: a quote the
household never wrote, a number that isn't in the quote (V-09), a value Kako already holds, a change
that starts before the fact it replaces, an attribute only a plan sets, a life event Kako has.
Nothing is written: the tool only holds what the turn keeps as pending.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from kako.agents.brief import BriefInputs, LifeEventView, render_brief
from kako.agents.numbers import check_texts
from kako.agents.proposing import HeldChange, hypothetical, parse_stated, proposal_tool
from kako.agents.tool_loop import ToolInputError
from kako.agents.tools import TurnState
from kako.engine import compute
from kako.facts.proposals import parse_fact, parse_life_event
from kako.facts.snapshot import take_snapshot
from tests.support.facts import HOUSEHOLD
from tests.support.villanueva import Villanueva, build

NOV_20 = date(2026, 11, 20)
BEFORE_THE_JOB = datetime(2026, 11, 20, 11, tzinfo=UTC)  # 7 PM in Manila
MESSAGE = (
    "Mara here, with news: I got a new job! I start on Dec 1, and my take-home pay will be "
    "₱68,000 a month."
)
QUOTE = "I start on Dec 1, and my take-home pay will be ₱68,000 a month."
SALARY = {
    "entity": "income:mara-s-salary",
    "attribute": "income.monthly_net",
    "value": "68000",
    "valid_from": "2026-12-01",
}
NEW_JOB = {"kind": "new_job", "description": "Mara starts a new job", "occurs_on": "2026-12-01"}


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _state(h: Villanueva, message: str = MESSAGE, **extra: Any) -> TurnState:
    snap = take_snapshot(HOUSEHOLD, h.facts, NOV_20, BEFORE_THE_JOB)
    inputs = BriefInputs(
        household_name="Villanueva household",
        people=(("Jun", "adult"), ("Mara", "adult")),
        entities=tuple(h.entities),
        snapshot=snap,
        run=compute(snap, h.entities),
        message=message,
        **extra,
    )
    return TurnState(render_brief(inputs, 3_000), inputs, "s4:t1", said_on=NOV_20)


async def _propose(state: TurnState, **arguments: Any) -> str:
    args = {"quote": QUOTE, "life_event": None, "facts": [], **arguments}
    result = await proposal_tool(state).run(args)
    return result.content


async def test_a_new_job_and_its_salary_are_held_for_a_yes(house: Villanueva) -> None:
    state = _state(house)
    shown = await _propose(state, life_event=NEW_JOB, facts=[SALARY])
    assert shown == (
        "C1, waiting for the household's yes (nothing changes until then):\n"
        "- Life event (new_job) on Dec 1, 2026: Mara starts a new job\n"
        "- Mara's salary: income.monthly_net = ₱68,000.00 from Dec 1, 2026, replacing ₱52,000.00 "
        "(since Mar 1, 2026)"
    )
    (change,) = state.proposed
    assert isinstance(change, HeldChange)
    assert change.quote == QUOTE
    event, salary = change.proposals
    written = parse_life_event(event.payload)
    assert (written.kind, written.occurs_on, written.source_ref) == (
        "new_job",
        date(2026, 12, 1),
        "s4:t1",
    )
    fact = parse_fact(salary.kind, salary.payload)
    old = state.snapshot.get(fact.entity_id, "income.monthly_net")
    assert old is not None
    assert (salary.kind, fact.value, fact.replaces, fact.life_event_id) == (
        "replace_fact",
        6_800_000,
        old.id,
        written.id,
    )
    assert str(written.id) not in shown  # ids never reach a model: a recording replays anywhere


@pytest.mark.parametrize(
    ("arguments", "refusal"),
    [
        ({"quote": "I got a promotion"}, "copied exactly from its message"),
        ({"facts": [{**SALARY, "value": "68500"}]}, "not found: the value ₱68,500.00"),
        ({"facts": [{**SALARY, "valid_from": "2027-01-01"}]}, "not found: valid_from 2027-01-01"),
        ({"facts": [{**SALARY, "value": "52000"}]}, "is ₱52,000.00 already"),
        ({"facts": [{**SALARY, "valid_from": "2026-02-01"}]}, "a change starts later"),
        (
            {"facts": [{**SALARY, "attribute": "plan.allocation", "entity": "debt:credit-card"}]},
            "can't be proposed",
        ),
        ({"facts": [{**SALARY, "entity": "debt:credit-card"}]}, "this needs one of: income"),
        ({"facts": [{**SALARY, "value": "sixty-eight thousand"}]}, "income.monthly_net"),
        ({"life_event": {**NEW_JOB, "kind": "lottery"}}, "life_event.kind is one of"),
        ({}, "propose a life event, facts, or both"),
    ],
)
async def test_what_a_model_gets_wrong_is_refused(
    house: Villanueva, arguments: dict[str, Any], refusal: str
) -> None:
    state = _state(house)
    with pytest.raises(ToolInputError, match=refusal):
        await _propose(state, **arguments)
    assert state.proposed == []


async def test_a_life_event_kako_has_is_not_proposed_again(house: Villanueva) -> None:
    known = (LifeEventView("new_job", "Mara starts a new job", date(2026, 12, 1)),)
    state = _state(house, life_events=known)
    with pytest.raises(ToolInputError, match="already has a new_job life event on Dec 1, 2026"):
        await _propose(state, life_event=NEW_JOB)


async def test_one_turn_holds_two_changes_at_most_and_each_fact_once(house: Villanueva) -> None:
    state = _state(house)
    await _propose(state, facts=[SALARY])
    with pytest.raises(ToolInputError, match="already proposed in this turn"):
        await _propose(state, facts=[SALARY])
    message = MESSAGE + " Food is ₱22,000 a month now."
    state = _state(house, message=message)
    await _propose(state, facts=[SALARY])
    food = {
        "entity": "expense:food",
        "attribute": "expense.monthly_amount",
        "value": "₱22,000",
        "valid_from": "2026-11-20",  # the household's date: "now"
    }
    shown = await _propose(state, quote="Food is ₱22,000 a month now.", facts=[food])
    assert "Food: expense.monthly_amount = ₱22,000.00 from Nov 20, 2026" in shown
    with pytest.raises(ToolInputError, match="at most 2 changes a turn"):
        await _propose(state, facts=[SALARY])


def test_the_tool_schema_is_strict(house: Villanueva) -> None:
    schema = json.dumps(proposal_tool(_state(house)).spec.parameters, ensure_ascii=False)
    assert '"additionalProperties": false' in schema
    assert "plan.allocation" not in schema


@pytest.mark.parametrize(
    ("attribute_key", "text", "value"),
    [
        ("income.monthly_net", "₱68,000", 6_800_000),
        ("income.monthly_net", "PHP 68,000.50", 6_800_050),
        ("debt.monthly_rate", "3.5%", Decimal("0.035")),
        ("debt.monthly_rate", "0.03", Decimal("0.03")),
        ("goal.priority", "1", 1),
        ("goal.target_date", "2031-12-01", date(2031, 12, 1)),
        ("expense.essential", "yes", "yes"),
    ],
)
def test_values_as_the_household_writes_them(attribute_key: str, text: str, value: object) -> None:
    assert parse_stated(attribute_key, text) == value


async def test_what_a_turn_proposed_may_be_named_in_its_reply(house: Villanueva) -> None:
    """The reply can tell the household what waits for its yes: the proposed day and amount are
    numbers the number check knows, as the household's own (checked) words."""
    state = _state(house, message="My take-home pay will be ₱68,000 a month from Jan 15.")
    reply = "I've proposed ₱68,000 a month from Jan 15, 2027."
    (before,) = check_texts(state, [("reply", "the reply", reply)])
    assert [n.text for n in before.unmatched] == ["Jan 15, 2027"]
    salary = {**SALARY, "valid_from": "2027-01-15"}
    await _propose(state, quote=state.message, facts=[salary])
    (after,) = check_texts(state, [("reply", "the reply", reply)])
    assert after.unmatched == ()
    assert {n.match for n in after.numbers} == {"proposed:C1"}


@pytest.mark.parametrize(
    ("message", "quote", "what_if"),
    [
        ("what if i lose my job", "i lose my job", True),
        ("What if Jun loses the job?", "Jun loses the job", True),
        ("Suppose Mara gets a raise to ₱70,000.", "Mara gets a raise to ₱70,000", True),
        ("If I lose my job next month, how long does the fund last?", "I lose my job", True),
        ("Paano kung mawalan ng trabaho si Jun?", "mawalan ng trabaho si Jun", True),
        ("Let's say my salary goes to 200000 per month.", "my salary goes to 200000", True),
        (MESSAGE, QUOTE, False),
        (
            "I lost my job yesterday. What if we pause the extra on the card?",
            "I lost my job",
            False,
        ),
        ("If it helps: my pay went up to ₱70,000 this month.", "my pay went up to ₱70,000", False),
        ("I got a raise, in case you didn't know: ₱70,000 now.", "I got a raise", False),
        ("What would happen if Mara stops working?", "Mara stops working", True),
    ],
)
def test_a_what_if_is_told_from_news(message: str, quote: str, what_if: bool) -> None:
    assert hypothetical(message, quote) is what_if


async def test_a_what_if_is_never_filed_as_a_change(house: Villanueva) -> None:
    """Pim's sandbox, Nov 25: "what if i lose my job" was filed as Jun's job loss, for a yes."""
    message = "What if Jun loses the job?"
    state = _state(house, message=message)
    loss = {"kind": "job_loss", "description": "Jun loses the job", "occurs_on": "2026-12-01"}
    with pytest.raises(ToolInputError, match="those words ask a what-if: nothing has happened"):
        await _propose(state, quote="Jun loses the job", life_event=loss)
    assert state.proposed == []
