"""The specialists and the orchestrator on the worked example, with a scripted model.

Phase 3, task 3, done when: the session-2 question ("how hard should we pay down the card?")
produces options A and B with the worked example's figures, cited. The model is scripted (no
network, no Azure): it names allocations as specs and refs, and every figure in the answer comes
from the engine through the tools. A: all ₱9,050 on the card, paid off in 9 months with ₱12,460.10
of interest. B: Jun's ₱4,000 on the card and the rest (₱5,050, worked out in code) to the emergency
fund: 17 months, ₱24,303.62, and the fund's target in 12 months (docs/data-model.md).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from kako.agents.answers import Citation, TurnAnswer
from kako.agents.brief import BriefInputs, render_brief
from kako.agents.chat import ChatRequest
from kako.agents.model_manager import ModelManager
from kako.agents.orchestrator import answer_turn
from kako.agents.recorded import RecordingBackend, ReplayBackend
from kako.agents.specialists import shared_rules, system_prompt
from kako.agents.spend import MemoryLlmLog
from kako.agents.tools import TurnState
from kako.agents.turn import MemoryStepLog
from kako.engine import compute
from kako.facts.snapshot import take_snapshot
from tests.conftest import MakeSettings
from tests.support.facts import HOUSEHOLD
from tests.support.models import ScriptedBackend, calls, says
from tests.support.villanueva import SEP_15, Villanueva, build

SEED = "s2:t1"
# Session 2, Sep 15, before the household chose B (plan v2 was accepted that evening).
BEFORE_PLAN_V2 = datetime(2026, 9, 15, 1, tzinfo=UTC)
SESSION_2 = (
    "Mara here. How hard should we pay down the credit card? Jun thinks ₱4,000 extra a month is "
    "enough and the rest can go to the emergency fund, but I'd rather clear the card fast."
)

CARD_PAYOFF = "debt.payoff_months@debt:credit-card"
CARD_INTEREST = "debt.total_interest@debt:credit-card"
ALL_ON_CARD = [
    {"entity": "debt:credit-card", "amount": "figure:cashflow.monthly_surplus"},
    {"entity": "account:emergency-fund", "amount": "none"},
]
SPLIT = [
    {"entity": "debt:credit-card", "amount": "said:4000"},
    {"entity": "account:emergency-fund", "amount": "rest"},
]


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _state(h: Villanueva, message: str = SESSION_2) -> TurnState:
    snap = take_snapshot(HOUSEHOLD, h.facts, SEP_15, BEFORE_PLAN_V2)
    inputs = BriefInputs(
        household_name="Villanueva household",
        people=(("Jun", "adult"), ("Mara", "adult"), ("Lia", "child")),
        entities=tuple(h.entities),
        snapshot=snap,
        run=compute(snap, h.entities),
        message=message,
    )
    return TurnState(render_brief(inputs, 3_000), inputs, SEED)


def _session_2_script() -> dict[str, Any]:
    return {
        f"{SEED}/orchestrator/1": calls(
            (
                "ask_debt",
                {
                    "question": "How hard should they pay down the card? Try the whole surplus on "
                    "it, and Jun's amount with the rest to the emergency fund."
                },
            ),
            (
                "ask_savings",
                {"question": "What does Jun's split do for the emergency fund's target?"},
            ),
        ),
        f"{SEED}/debt#1/1": calls(
            ("run_what_if", {"allocations": ALL_ON_CARD}),
            ("run_what_if", {"allocations": SPLIT}),
        ),
        f"{SEED}/debt#1/2": calls(
            (
                "submit_proposal",
                {
                    "summary": "Avalanche order puts the card first. All of the surplus on it "
                    "pays it off in 9 months with ₱12,460.10 of interest.",
                    "what_if": "debt1-W1",
                    "sources": [
                        f"figure:debt1-W1:{CARD_PAYOFF}",
                        f"figure:debt1-W1:{CARD_INTEREST}",
                        "fact:preference.debt_strategy",
                    ],
                },
            )
        ),
        f"{SEED}/savings#1/1": calls(("run_what_if", {"allocations": SPLIT})),
        f"{SEED}/savings#1/2": calls(
            (
                "submit_proposal",
                {
                    "summary": "The runway is 2.1 months. Jun's split reaches the 3-month "
                    "target in 12 months.",
                    "what_if": "savings1-W1",
                    "sources": [
                        "figure:savings1-W1:savings.months_to_target",
                        "figure:savings.emergency_runway_months",
                        "said",
                    ],
                },
            )
        ),
        f"{SEED}/orchestrator/2": calls(
            (
                "submit_answer",
                {
                    "reply": "Two ways to go. A clears the card fastest; B keeps building cash "
                    "for Lia's school year while still paying the card down.",
                    "options": [
                        {
                            "label": "A: all extra on the card",
                            "what_if": "debt1-W1",
                            "summary": "Card paid off in 9 months, ₱12,460.10 of interest.",
                            "sources": [
                                f"figure:debt1-W1:{CARD_PAYOFF}",
                                f"figure:debt1-W1:{CARD_INTEREST}",
                                "fact:preference.debt_strategy",
                            ],
                            "specialists": ["debt"],
                        },
                        {
                            "label": "B: split",
                            "what_if": "savings1-W1",
                            "summary": "Card paid off in 17 months, ₱24,303.62 of interest; the "
                            "emergency fund reaches its target in 12 months.",
                            "sources": [
                                f"figure:savings1-W1:{CARD_PAYOFF}",
                                f"figure:savings1-W1:{CARD_INTEREST}",
                                "figure:savings1-W1:savings.months_to_target",
                                "said",
                            ],
                            "specialists": ["debt", "savings"],
                        },
                    ],
                    "recommended": "",
                    "resolution": {
                        "what_if": "",
                        "rejected": "",
                        "reason": "Mara wants the card cleared fast and Jun wants cash on hand. "
                        "A and B each fit the surplus on its own, so the choice is yours.",
                    },
                },
            )
        ),
    }


def _manager(
    make_settings: MakeSettings, script: dict[str, Any]
) -> tuple[ModelManager, ScriptedBackend]:
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    backend = ScriptedBackend(script)
    return ModelManager(settings, backend, MemoryLlmLog()), backend


def _figures(citations: tuple[Citation, ...]) -> dict[str, Any]:
    return {c.ref: c.figure.value for c in citations if c.figure is not None}


def _request(backend: ScriptedBackend, key: str) -> ChatRequest:
    return next(r for k, _, r in backend.requests if k == key)


async def test_session_2_gives_options_a_and_b_with_the_worked_examples_figures(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    state = _state(house)
    manager, _ = _manager(make_settings, _session_2_script())
    steps = MemoryStepLog()
    turn = manager.turn(SEED, steps=steps)
    answer = await answer_turn(manager, turn, state)

    assert isinstance(answer, TurnAnswer)
    assert [o.label for o in answer.options] == ["A: all extra on the card", "B: split"]
    assert answer.recommended is None  # the choice is the household's
    a, b = answer.options
    card, fund = house.ids["card"], house.ids["fund"]

    # A: the whole surplus on the card, named as a figure; nothing to the fund.
    assert {(x.entity_id, x.centavos, x.spec) for x in a.allocations} == {
        (card, 905_000, "figure:cashflow.monthly_surplus"),
        (fund, 0, "none"),
    }
    assert _figures(a.citations) == {
        f"figure:debt1-W1:{CARD_PAYOFF}": 9,
        f"figure:debt1-W1:{CARD_INTEREST}": 1_246_010,  # ₱12,460.10
    }
    assert [c.shown for c in a.citations] == ["9 months", "₱12,460.10", "avalanche"]

    # B: Jun's ₱4,000 from the message, and the rest (₱5,050) worked out in code.
    assert {(x.entity_id, x.centavos, x.spec) for x in b.allocations} == {
        (card, 400_000, "said:4000"),
        (fund, 505_000, "rest"),
    }
    assert _figures(b.citations) == {
        f"figure:savings1-W1:{CARD_PAYOFF}": 17,
        f"figure:savings1-W1:{CARD_INTEREST}": 2_430_362,  # ₱24,303.62
        "figure:savings1-W1:savings.months_to_target": 12,
    }
    assert b.citations[-1].kind == "conversation"
    assert b.citations[-1].shown == SESSION_2
    assert b.specialists == ("debt", "savings")

    # Each option's figures are its what-if's, which the engine ran with those allocations.
    for option in answer.options:
        run = state.what_ifs[option.what_if].run
        for citation in option.citations:
            if citation.figure is not None:
                assert run.get(citation.figure.key, citation.figure.entity_id) == citation.figure
                assert citation.what_if == option.what_if

    # Every specialist's proposal is kept, in the order asked.
    assert [p.specialist for p in answer.proposals] == ["debt", "savings"]
    assert answer.proposals[0].what_if == "debt1-W1"
    # debt1-W1, debt1-W2, savings1-W1, and the two proposals together (rec-W1)
    assert list(state.what_ifs) == ["debt1-W1", "debt1-W2", "savings1-W1", "rec-W1"]

    # Together, A's ₱9,050 on the card and B's ₱5,050 to the fund are over the ₱9,050 surplus:
    # code found it, and the orchestrator left the choice to the household (Mara and Jun differ).
    resolution = answer.resolution
    assert resolution is not None
    assert [c.kind for c in resolution.conflicts] == ["over_allocation"]
    assert resolution.described == (
        "over-allocation (debt, savings): together they allocate ₱5,050.00 a month more than the "
        "surplus (figure:cashflow.monthly_surplus = ₱9,050.00; "
        "figure:rec-W1:plan.unallocated = -₱5,050.00 (negative))",
    )
    assert {(a.entity_id, a.centavos, a.spec) for a in resolution.together_allocations} == {
        (card, 905_000, "ask:debt1-W1"),
        (fund, 505_000, "ask:savings1-W1"),
    }
    assert (resolution.chosen, resolution.rejected, resolution.attempts) == (None, None, 0)
    assert resolution.reason.startswith("Mara wants the card cleared fast")

    # Every tool call is an agent step: the specialists' own, then the orchestrator's asks.
    assert [(s.agent, s.tool, s.outcome) for s in steps.steps] == [
        ("debt", "run_what_if", "ok"),
        ("debt", "run_what_if", "ok"),
        ("savings", "run_what_if", "ok"),
        ("debt", "submit_proposal", "ok"),
        ("savings", "submit_proposal", "ok"),
        ("orchestrator", "ask_debt", "ok"),
        ("orchestrator", "ask_savings", "ok"),
        ("orchestrator", "submit_answer", "ok"),
    ]
    assert [s.seq for s in steps.steps] == list(range(1, 9))
    assert steps.steps[0].result_summary == (
        "debt1-W1: account:emergency-fund ₱0.00, debt:credit-card ₱9,050.00; "
        "debt:credit-card paid off in 9 months"
    )


async def test_what_each_agent_was_sent(house: Villanueva, make_settings: MakeSettings) -> None:
    state = _state(house)
    manager, backend = _manager(make_settings, _session_2_script())
    await answer_turn(manager, manager.turn(SEED), state)

    deployments = {k.split("/")[1]: d for k, d, _ in backend.requests}
    assert deployments == {
        "orchestrator": "kako-strong",
        "debt#1": "kako-fast",
        "savings#1": "kako-fast",
    }

    # The shared rules and the brief come first in every system prompt (one cached prefix).
    prefix = f"{shared_rules()}\n\n{state.brief.text}\n\n"
    for key in (f"{SEED}/orchestrator/1", f"{SEED}/debt#1/1", f"{SEED}/savings#1/1"):
        system = _request(backend, key).messages[0].content or ""
        assert system.startswith(prefix)
    assert "Your role: the debt specialist" in system_prompt("debt", state.brief)
    assert "{glossary}" not in shared_rules()
    assert "- `debt.payoff_months`: months until the debt is paid off" in shared_rules()

    # The household's message and the orchestrator's question are data, never instructions.
    debt_user = _request(backend, f"{SEED}/debt#1/1").messages[1].content or ""
    assert '<data source="orchestrator">How hard should they pay down the card?' in debt_user
    assert '<data source="household">Mara here.' in debt_user

    # The specialist saw the engine's figures for its what-ifs, never a number it worked out.
    seen = "\n".join(
        m.content or "" for m in _request(backend, f"{SEED}/debt#1/2").messages if m.role == "tool"
    )
    assert "What-if debt1-W1: account:emergency-fund gets ₱0.00 a month (none)" in seen
    assert "account:emergency-fund gets ₱5,050.00 a month (rest)" in seen
    assert f"- {CARD_PAYOFF} = 9 months" in seen
    assert f"- {CARD_PAYOFF} = 17 months" in seen

    # The orchestrator read each proposal with what it cited.
    read = "\n".join(
        m.content or ""
        for m in _request(backend, f"{SEED}/orchestrator/2").messages
        if m.role == "tool"
    )
    assert "The debt specialist proposes (what-if debt1-W1):" in read
    assert f"- figure:debt1-W1:{CARD_INTEREST} = ₱12,460.10" in read
    assert "Allocations: account:emergency-fund ₱5,050.00 a month (rest)" in read

    # Strict schemas for every tool the orchestrator is offered.
    tools = _request(backend, f"{SEED}/orchestrator/1").tools
    assert [t.name for t in tools] == [
        "get_figures",
        "get_facts",
        "get_decisions",
        "run_what_if",
        "ask_budget",
        "ask_debt",
        "ask_savings",
        "ask_goals",
        "propose_change",
        "submit_answer",
    ]
    for tool in tools:
        assert tool.strict
        assert tool.parameters["additionalProperties"] is False
        assert set(tool.parameters["required"]) == set(tool.parameters["properties"])


async def test_a_refused_answer_is_fixed_and_handed_in_again(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    """Code refuses an option that cites no figure of its own what-if; the model is told why."""
    state = _state(house)
    script = _session_2_script()
    good = json.loads(script[f"{SEED}/orchestrator/2"].tool_calls[0].arguments)
    bad = json.loads(json.dumps(good))
    bad["options"][1]["sources"] = [f"figure:debt1-W1:{CARD_PAYOFF}", "said"]  # A's figure
    script[f"{SEED}/orchestrator/2"] = calls(("submit_answer", bad))
    script[f"{SEED}/orchestrator/3"] = calls(("submit_answer", good))
    manager, backend = _manager(make_settings, script)
    steps = MemoryStepLog()
    answer = await answer_turn(manager, manager.turn(SEED, steps=steps), state)

    assert [o.label for o in answer.options] == ["A: all extra on the card", "B: split"]
    assert [s.outcome for s in steps.steps if s.tool == "submit_answer"] == ["error", "ok"]
    refusal = _request(backend, f"{SEED}/orchestrator/3").messages[-1].content or ""
    assert "option 'B: split': cite at least one figure of savings1-W1" in refusal


async def test_at_most_four_specialist_asks_a_turn(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    state = _state(house)
    asks = [("ask_budget", {"question": f"Look {n}"}) for n in range(5)]
    script: dict[str, Any] = {
        f"{SEED}/orchestrator/1": calls(*asks),
        f"{SEED}/orchestrator/2": says("Here is what the budget looks like."),
    }
    for n in range(1, 5):
        script[f"{SEED}/budget#{n}/1"] = calls(
            (
                "submit_proposal",
                {
                    "summary": "The surplus is ₱9,050.00, all of it unallocated.",
                    "what_if": "",
                    "sources": ["figure:cashflow.monthly_surplus", "said"],
                },
            )
        )
    manager, _ = _manager(make_settings, script)
    steps = MemoryStepLog()
    answer = await answer_turn(manager, manager.turn(SEED, steps=steps), state)

    asked = [s for s in steps.steps if s.tool == "ask_budget"]
    assert [s.outcome for s in asked] == ["ok", "ok", "ok", "ok", "error"]
    assert "limit of 4 specialist asks" in asked[-1].result_summary
    assert answer.options == ()
    assert answer.reply == "Here is what the budget looks like."
    assert [p.specialist for p in answer.proposals] == ["budget"] * 4
    assert all(p.what_if is None and p.allocations == () for p in answer.proposals)


async def test_a_parallel_turn_records_and_replays_strictly(
    house: Villanueva, make_settings: MakeSettings, tmp_path: Path
) -> None:
    """The specialists run at the same time; each sends the same requests on replay, byte for
    byte, because what-if refs and what each one sees don't depend on timing."""
    path = tmp_path / "session-2.json"
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    live = ModelManager(
        settings, RecordingBackend(ScriptedBackend(_session_2_script()), path), MemoryLlmLog()
    )
    recorded = await answer_turn(live, live.turn(SEED), _state(house))

    replay = ReplayBackend(path)  # strict: a changed request is refused
    replayer = ModelManager(make_settings(), replay, MemoryLlmLog())
    replayed = await answer_turn(replayer, replayer.turn(SEED), _state(house))
    assert replay.drifted == []
    assert [(o.label, o.allocations) for o in replayed.options] == [
        (o.label, o.allocations) for o in recorded.options
    ]
    assert [c.shown for o in replayed.options for c in o.citations] == [
        c.shown for o in recorded.options for c in o.citations
    ]
