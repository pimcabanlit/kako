"""Reconciliation and the what-if loop on the worked example, with a scripted model.

Phase 3, task 4, done when: an over-allocation on the worked example is caught, at least one split
is tried and logged as an `agent_step`, and the resolution is shown with the rejected option.

Session 2 (Sep 15, surplus ₱9,050), as if Mara and Jun had agreed to keep cash on hand: the debt
specialist asks all ₱9,050 for the card and the savings specialist all ₱9,050 for the emergency
fund. Together that is ₱18,100 a month. Code finds it, the orchestrator tries Jun's ₱4,000 with
the whole surplus to the fund (refused: still over) and then with the rest to the fund (fits), and
resolves with that split, rejecting all-on-the-card.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest

from kako.agents.ask import Asked, render_answer
from kako.agents.orchestrator import answer_turn
from kako.agents.turn import MemoryStepLog
from tests.conftest import MakeSettings
from tests.support.models import calls, says
from tests.support.villanueva import Villanueva, build
from tests.test_agents_turn import (
    ALL_ON_CARD,
    CARD_PAYOFF,
    SEED,
    _manager,
    _request,
    _session_2_script,
    _state,
)

AGREED = (
    "Jun here. Mara and I agreed to keep cash on hand while Lia starts school. How hard should we "
    "pay down the credit card? We were thinking ₱4,000 extra a month."
)
ALL_TO_FUND = [
    {"entity": "account:emergency-fund", "amount": "figure:cashflow.monthly_surplus"},
    {"entity": "debt:credit-card", "amount": "none"},
]
OVER = [
    {"entity": "debt:credit-card", "amount": "said:4000"},
    {"entity": "account:emergency-fund", "amount": "figure:cashflow.monthly_surplus"},
]
SPLIT = [
    {"entity": "debt:credit-card", "amount": "said:4000"},
    {"entity": "account:emergency-fund", "amount": "rest"},
]
RESOLVED = {
    "what_if": "orch-W2",
    "rejected": "debt1-W1",
    "reason": "You agreed to keep cash on hand while Lia starts school, so the card gets the "
    "₱4,000 you named and the rest goes to the emergency fund.",
}


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _answer(**changes: Any) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "reply": "B pays the card down and keeps building the emergency fund, as you agreed.",
        "options": [
            {
                "label": "A: all extra on the card",
                "what_if": "debt1-W1",
                "summary": "Card paid off in 9 months, ₱12,460.10 of interest.",
                "sources": [f"figure:debt1-W1:{CARD_PAYOFF}", "fact:preference.debt_strategy"],
                "specialists": ["debt"],
            },
            {
                "label": "B: ₱4,000 on the card",
                "what_if": "orch-W2",
                "summary": "Card paid off in 17 months; the fund reaches its target in 12 months.",
                "sources": [
                    f"figure:orch-W2:{CARD_PAYOFF}",
                    "figure:orch-W2:savings.months_to_target",
                    "said",
                ],
                "specialists": ["debt", "savings"],
            },
        ],
        "recommended": "B: ₱4,000 on the card",
        "resolution": RESOLVED,
    }
    answer.update(changes)
    return answer


def _script(*, answer: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        f"{SEED}/orchestrator/1": calls(
            ("ask_debt", {"question": "How fast can the card go with the whole surplus?"}),
            ("ask_savings", {"question": "What would the whole surplus do for the fund?"}),
        ),
        f"{SEED}/debt#1/1": calls(("run_what_if", {"allocations": ALL_ON_CARD})),
        f"{SEED}/debt#1/2": calls(
            (
                "submit_proposal",
                {
                    "summary": "All of the surplus on the card pays it off in 9 months.",
                    "what_if": "debt1-W1",
                    "sources": [f"figure:debt1-W1:{CARD_PAYOFF}", "fact:preference.debt_strategy"],
                },
            )
        ),
        f"{SEED}/savings#1/1": calls(("run_what_if", {"allocations": ALL_TO_FUND})),
        f"{SEED}/savings#1/2": calls(
            (
                "submit_proposal",
                {
                    "summary": "All of the surplus to the fund reaches the target soonest.",
                    "what_if": "savings1-W1",
                    "sources": ["figure:savings1-W1:savings.months_to_target", "said"],
                },
            )
        ),
        f"{SEED}/orchestrator/2": calls(("run_what_if", {"allocations": OVER})),
        f"{SEED}/orchestrator/3": calls(("run_what_if", {"allocations": SPLIT})),
        f"{SEED}/orchestrator/4": calls(("submit_answer", answer or _answer())),
    }


async def test_an_over_allocation_is_caught_split_and_resolved(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    state = _state(house, AGREED)
    manager, backend = _manager(make_settings, _script())
    steps = MemoryStepLog()
    answer = await answer_turn(manager, manager.turn(SEED, steps=steps), state)
    card, fund = house.ids["card"], house.ids["fund"]

    # Caught: the two asks together are ₱18,100 a month against ₱9,050.
    resolution = answer.resolution
    assert resolution is not None
    [conflict] = resolution.conflicts
    assert conflict.kind == "over_allocation"
    assert conflict.specialists == ("debt", "savings")
    assert state.what_ifs["rec-W1"].run.value("plan.unallocated") == -905_000

    # The orchestrator was told, by code, with the figures.
    note = _request(backend, f"{SEED}/orchestrator/2").messages[-1]
    assert note.role == "user"
    assert note.content is not None
    assert note.content.startswith("Kako's reconciliation rules (code, not the household)")
    assert "together they allocate ₱9,050.00 a month more than the surplus" in note.content
    assert "figure:rec-W1:plan.unallocated = -₱9,050.00 (negative)" in note.content

    # Two splits tried, each an agent step: the first refused by the rules, the second fits.
    splits = [s for s in steps.steps if s.agent == "orchestrator" and s.tool == "run_what_if"]
    assert [s.outcome for s in splits] == ["rejected", "ok"]
    assert splits[0].result_summary.startswith("split 1: orch-W1: ")
    assert splits[0].result_summary.endswith("refused")
    assert splits[1].result_summary.endswith("fits")
    refused = _request(backend, f"{SEED}/orchestrator/3").messages[-1].content or ""
    assert "Split 1 of 3: the rules refuse orch-W1:" in refused
    fitted = _request(backend, f"{SEED}/orchestrator/4").messages[-1].content or ""
    assert "Split 2 of 3: orch-W2 fits." in fitted
    assert [(s.what_if, s.fits) for s in resolution.splits] == [
        ("orch-W1", False),
        ("orch-W2", True),
    ]
    assert resolution.attempts == 2

    # Resolved with the split, recommended, and the option it rejected kept with its allocations.
    assert (resolution.chosen, resolution.rejected) == ("orch-W2", "debt1-W1")
    assert answer.recommended == "B: ₱4,000 on the card"
    assert {(a.entity_id, a.centavos) for a in state.what_ifs["orch-W2"].allocations} == {
        (card, 400_000),
        (fund, 505_000),
    }
    assert {(a.entity_id, a.centavos) for a in resolution.rejected_allocations} == {
        (card, 905_000),
        (fund, 0),
    }

    # Shown: `kako ask` prints the conflict, the splits, the choice and the rejected option.
    shown = render_answer(Asked(answer, uuid.uuid4(), SEED, 0, 0, 0, Decimal(0)))
    assert "Reconciled in code (the proposals together, rec-W1):" in shown
    assert "  Split 1: orch-W1 refused (over-allocation)" in shown
    assert "  Split 2: orch-W2 fits" in shown
    assert "  Chosen: orch-W2. You agreed to keep cash on hand" in shown
    assert (
        "  Rejected: debt1-W1: account:emergency-fund ₱0.00 a month; "
        "debt:credit-card ₱9,050.00 a month"
    ) in shown


async def test_at_most_three_splits(house: Villanueva, make_settings: MakeSettings) -> None:
    script = _script()
    script[f"{SEED}/orchestrator/2"] = calls(*[("run_what_if", {"allocations": OVER})] * 4)
    script[f"{SEED}/orchestrator/3"] = calls(
        (
            "submit_answer",
            _answer(
                options=_answer()["options"][:1],
                recommended="",
                resolution={
                    "what_if": "",
                    "rejected": "",
                    "reason": "No split fitted, so the choice is yours.",
                },
            ),
        )
    )
    del script[f"{SEED}/orchestrator/4"]
    manager, _ = _manager(make_settings, script)
    steps = MemoryStepLog()
    answer = await answer_turn(manager, manager.turn(SEED, steps=steps), _state(house, AGREED))

    splits = [s for s in steps.steps if s.agent == "orchestrator" and s.tool == "run_what_if"]
    assert [s.outcome for s in splits] == ["rejected", "rejected", "rejected", "error"]
    assert "3 splits tried" in splits[-1].result_summary
    assert answer.resolution is not None
    assert answer.resolution.attempts == 3
    assert (answer.resolution.chosen, answer.resolution.rejected) == (None, None)


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [
        ({"resolution": None}, "code found conflicts (see its note): give a resolution"),
        (
            {"resolution": {**RESOLVED, "what_if": "orch-W1"}},
            "the resolution's what_if 'orch-W1' must be one of your options",
        ),
        ({"recommended": "A: all extra on the card"}, "recommend 'B: ₱4,000 on the card'"),
        ({"resolution": {**RESOLVED, "rejected": ""}}, "name the what-if you did not take"),
        ({"resolution": {**RESOLVED, "rejected": "rec-W1"}}, "rejected 'rec-W1' must be another"),
        (
            {"resolution": {**RESOLVED, "what_if": "", "rejected": ""}},
            "you recommend an option while a conflict is open",
        ),
        ({"resolution": {**RESOLVED, "what_if": "", "rejected": "debt1-W1"}}, "rejected is"),
        ({"resolution": {**RESOLVED, "reason": " "}}, "reason must be a non-empty string"),
    ],
)
async def test_a_resolution_is_checked_in_code(
    house: Villanueva, make_settings: MakeSettings, changes: dict[str, Any], refusal: str
) -> None:
    script = _script(answer=_answer(**changes))
    script[f"{SEED}/orchestrator/5"] = calls(("submit_answer", _answer()))
    manager, backend = _manager(make_settings, script)
    steps = MemoryStepLog()
    answer = await answer_turn(manager, manager.turn(SEED, steps=steps), _state(house, AGREED))

    assert [s.outcome for s in steps.steps if s.tool == "submit_answer"] == ["error", "ok"]
    told = _request(backend, f"{SEED}/orchestrator/5").messages[-1].content or ""
    assert refusal in json.loads(told)["error"]
    assert answer.resolution is not None
    assert answer.resolution.chosen == "orch-W2"


async def test_a_split_that_still_over_allocates_cant_resolve(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    """An option must fit the surplus, so the over-allocated split can't even be offered."""
    bad = _answer()
    bad["options"][1] = {
        **bad["options"][1],
        "what_if": "orch-W1",
        "sources": [f"figure:orch-W1:{CARD_PAYOFF}", "said"],
    }
    bad["resolution"] = {**RESOLVED, "what_if": "orch-W1"}
    script = _script(answer=bad)
    script[f"{SEED}/orchestrator/5"] = calls(("submit_answer", _answer()))
    manager, backend = _manager(make_settings, script)
    await answer_turn(manager, manager.turn(SEED), _state(house, AGREED))
    told = _request(backend, f"{SEED}/orchestrator/5").messages[-1].content or ""
    assert "orch-W1 allocates more than the surplus" in told


async def test_proposals_that_fit_together_need_no_resolution(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    """Debt asks ₱4,000 for the card, savings the rest for the fund: they fit. Code says so, and
    a resolution is refused because there is nothing to resolve."""
    script = _session_2_script()
    script[f"{SEED}/debt#1/2"] = calls(
        (
            "submit_proposal",
            {
                "summary": "Jun's ₱4,000 on the card pays it off in 17 months.",
                "what_if": "debt1-W2",
                "sources": [f"figure:debt1-W2:{CARD_PAYOFF}", "said"],
            },
        )
    )
    good = json.loads(script[f"{SEED}/orchestrator/2"].tool_calls[0].arguments)
    script[f"{SEED}/orchestrator/2"] = calls(("submit_answer", good))
    script[f"{SEED}/orchestrator/3"] = calls(("submit_answer", {**good, "resolution": None}))
    manager, backend = _manager(make_settings, script)
    steps = MemoryStepLog()
    state = _state(house)
    answer = await answer_turn(manager, manager.turn(SEED, steps=steps), state)

    note = _request(backend, f"{SEED}/orchestrator/2").messages[-1].content or ""
    assert "They fit together: no over-allocation, no opposite moves, no goal date missed." in note
    assert state.what_ifs["rec-W1"].run.value("plan.unallocated") == 0
    told = _request(backend, f"{SEED}/orchestrator/3").messages[-1].content or ""
    assert "code found no conflict to resolve: pass resolution null" in told
    assert answer.resolution is None
    assert [s.outcome for s in steps.steps if s.tool == "submit_answer"] == ["error", "ok"]


async def test_no_answer_shows_the_conflict_as_it_is(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    script = _script()
    script[f"{SEED}/orchestrator/2"] = says("You'll have to choose.")
    del script[f"{SEED}/orchestrator/3"], script[f"{SEED}/orchestrator/4"]
    manager, _ = _manager(make_settings, script)
    answer = await answer_turn(manager, manager.turn(SEED), _state(house, AGREED))
    assert answer.options == ()
    assert answer.resolution is not None
    assert answer.resolution.chosen is None
    assert answer.resolution.reason == "No resolution was given, so the conflict is shown as it is."
