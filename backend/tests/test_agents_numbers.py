"""The number check in a turn, with a scripted model: a text that fails is sent back once with the
numbers named (`regenerated`), and a second miss is kept with them flagged (`fail`), never silently.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest

from kako.agents.ask import Asked, render_answer
from kako.agents.checks import MemoryCheckLog
from kako.agents.orchestrator import answer_turn
from kako.agents.tools import TurnState
from kako.agents.turn import MemoryStepLog
from tests.conftest import MakeSettings
from tests.support.models import calls, says
from tests.support.villanueva import Villanueva, build
from tests.test_agents_turn import CARD_PAYOFF, SEED, _manager, _request, _session_2_script, _state


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _logged(house: Villanueva) -> tuple[TurnState, MemoryCheckLog]:
    state = _state(house)
    log = MemoryCheckLog()
    state.checks = log
    return state, log


def _good() -> dict[str, Any]:
    return json.loads(_session_2_script()[f"{SEED}/orchestrator/2"].tool_calls[0].arguments)


async def test_a_wrong_number_twice_is_shown_flagged(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    script = _session_2_script()
    bad = {**_good(), "reply": "A saves ₱11,843.52 of interest."}  # B's less A's: worked out
    worse = {**_good(), "reply": "A saves about ₱11,800 of interest."}
    script[f"{SEED}/orchestrator/2"] = calls(("submit_answer", bad))
    script[f"{SEED}/orchestrator/3"] = calls(("submit_answer", worse))
    manager, backend = _manager(make_settings, script)
    state, log = _logged(house)
    steps = MemoryStepLog()
    answer = await answer_turn(manager, manager.turn(SEED, steps=steps), state)

    assert answer.reply == worse["reply"]
    [reply] = [c for c in answer.checks if c.subject == "reply"]
    assert reply.result == "fail"
    assert [n.text for n in reply.unmatched] == ["₱11,800"]
    assert [(r.subject, r.result) for r in log.records if r.subject == "reply"] == [
        ("reply", "regenerated"),
    ]
    told = json.loads(_request(backend, f"{SEED}/orchestrator/3").messages[-1].content or "")
    assert "'₱11,843.52' in the reply" in told["error"]
    assert [s.outcome for s in steps.steps if s.tool == "submit_answer"] == ["error", "ok"]

    shown = render_answer(Asked(answer, uuid.uuid4(), SEED, 0, 0, 0, Decimal(0)))
    assert "Numbers that match no figure or fact (flagged): '₱11,800' in the reply" in shown


async def test_every_text_the_household_reads_is_checked(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    good = _good()
    bad = json.loads(json.dumps(good))
    bad["options"][0]["label"] = "A: card in 8 months"
    bad["options"][1]["summary"] = "Card paid off in 17 months, 8 months longer than A."
    bad["resolution"]["reason"] = "Both fit; A uses 100% of the ₱9,050.00."
    script = _session_2_script()
    script[f"{SEED}/orchestrator/2"] = calls(("submit_answer", bad))
    script[f"{SEED}/orchestrator/3"] = calls(("submit_answer", good))
    manager, backend = _manager(make_settings, script)
    state, log = _logged(house)
    answer = await answer_turn(manager, manager.turn(SEED), state)

    told = json.loads(_request(backend, f"{SEED}/orchestrator/3").messages[-1].content or "")
    assert "'8 months' in option 'A: card in 8 months''s label" in told["error"]
    assert "'8 months' in option 'B: split''s summary" in told["error"]
    assert "'100%' in the resolution's reason" in told["error"]
    assert "'₱9,050.00'" not in told["error"]  # the surplus: a figure
    regenerated = [r for r in log.records if r.result == "regenerated"]
    assert [r.subject for r in regenerated] == [
        "recommendation",
        "recommendation",
        "reconciliation",
    ]
    assert all(c.ok for c in answer.checks)
    assert [c.subject for c in answer.checks] == [
        "reply",
        *["recommendation"] * 4,
        "reconciliation",
    ]


async def test_a_specialists_summary_is_checked_too(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    script = _session_2_script()
    good = json.loads(script[f"{SEED}/debt#1/2"].tool_calls[0].arguments)
    bad = {**good, "summary": "All of the surplus clears the card 8 months sooner than Jun's."}
    script[f"{SEED}/debt#1/2"] = calls(("submit_proposal", bad))
    script[f"{SEED}/debt#1/3"] = calls(("submit_proposal", good))
    manager, backend = _manager(make_settings, script)
    state, log = _logged(house)
    answer = await answer_turn(manager, manager.turn(SEED), state)

    told = _request(backend, f"{SEED}/debt#1/3").messages[-1].content or ""
    assert "'8 months' in the debt specialist's summary" in told
    debt = [r for r in log.records if "debt" in r.checked_text or "card" in r.checked_text][:2]
    assert [(r.subject, r.result) for r in debt] == [
        ("recommendation", "regenerated"),
        ("recommendation", "pass"),
    ]
    assert answer.proposals[0].summary == good["summary"]
    assert answer.proposals[0].check is not None
    assert answer.proposals[0].check.ok


async def test_an_answer_sent_back_is_kept_if_the_model_stops(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    """Refused for its numbers, the orchestrator then only talks: its answer is still shown, with
    the number flagged, rather than lost."""
    script = _session_2_script()
    bad = {**_good(), "reply": "A is 8 months faster."}
    script[f"{SEED}/orchestrator/2"] = calls(("submit_answer", bad))
    script[f"{SEED}/orchestrator/3"] = says("Sorry, here it is again.")
    manager, _ = _manager(make_settings, script)
    state, _ = _logged(house)
    answer = await answer_turn(manager, manager.turn(SEED), state)
    assert answer.reply == "A is 8 months faster."
    assert [o.label for o in answer.options] == ["A: all extra on the card", "B: split"]
    assert [n.text for c in answer.checks for n in c.unmatched] == ["8 months"]


async def test_a_plain_reply_is_checked(house: Villanueva, make_settings: MakeSettings) -> None:
    script: dict[str, Any] = {
        f"{SEED}/orchestrator/1": says(f"The surplus is ₱9,050.00; see {CARD_PAYOFF}."),
    }
    manager, _ = _manager(make_settings, script)
    state, _ = _logged(house)
    answer = await answer_turn(manager, manager.turn(SEED), state)
    [check] = answer.checks
    assert [(n.text, n.match is not None) for n in check.numbers] == [("₱9,050.00", True)]
    assert check.ok
