"""The agent test set (Phase 3, tasks 7 and 8): the questions, what they expect, and the scoring.

Every number a question expects is held to the engine here, on the demo household as it was at the
question's time, so the set can't drift from the data. The scorer is run on session 2's scripted
turn (the orchestrator and its specialists) and on the single-agent baseline's, with no network.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from kako.agents.answers import Allocation, TurnAnswer
from kako.agents.brief import BriefInputs, render_brief
from kako.agents.checks import Number, TextCheck
from kako.agents.numbers import check_text, pool_of
from kako.agents.orchestrator import answer_turn
from kako.agents.single import answer_alone
from kako.agents.tools import TurnState
from kako.engine import compute
from kako.evals.questions import TEST_SET, Question, TestSetError, centavos, read_test_set
from kako.evals.scoring import current_allocations, score
from kako.facts.snapshot import take_snapshot
from tests.conftest import MakeSettings
from tests.support.facts import HOUSEHOLD
from tests.support.models import calls
from tests.support.villanueva import Villanueva, build
from tests.test_agents_turn import (
    ALL_ON_CARD,
    CARD_INTEREST,
    CARD_PAYOFF,
    SPLIT,
    _manager,
    _session_2_script,
)

QUESTIONS = read_test_set()
BY_ID = {q.id: q for q in QUESTIONS}


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _state(h: Villanueva, q: Question) -> TurnState:
    snap = take_snapshot(HOUSEHOLD, h.facts, q.on, q.known_at)
    inputs = BriefInputs(
        household_name="Villanueva household",
        people=(("Jun", "adult"), ("Mara", "adult"), ("Lia", "child")),
        entities=tuple(h.entities),
        snapshot=snap,
        run=compute(snap, h.entities),
        message=q.message,
    )
    return TurnState(render_brief(inputs, 3_000), inputs, q.seed)


def test_the_set_is_about_twenty_questions_over_the_story() -> None:
    assert 18 <= len(QUESTIONS) <= 25
    assert [q.id for q in QUESTIONS] == [f"q{n:02d}" for n in range(1, len(QUESTIONS) + 1)]
    assert len({q.message for q in QUESTIONS}) == len(QUESTIONS)
    # Every point in the story: before plan v2, after the preference, the November statements,
    # the new job before plan v3, and plan v3.
    assert len({(q.on, q.known_at) for q in QUESTIONS}) == 5
    assert all(q.expect != type(q.expect)() for q in QUESTIONS)  # each expects something


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_every_expected_number_is_the_engines(house: Villanueva, q: Question) -> None:
    """What a question expects is true of the household then: each number is a figure of the turn's
    run or of a move it expects, a fact, or the household's own words; each ref exists."""
    state = _state(house, q)
    refs = state.refs
    ids = {refs.entity(e.id): e.id for e in house.entities}
    current = current_allocations(state)
    moves = list(q.expect.allocations)
    if q.expect.not_recommended:
        moves.append(q.expect.not_recommended)
    for n, move in enumerate(moves, start=1):
        assert set(move) <= set(ids), move
        named = tuple(
            Allocation(ids[ref], ref, centavos(amount), "x") for ref, amount in move.items()
        )
        result = state.what_if(f"exp{n}", named)
        assert not result.over_allocated, f"{q.id}: {move} is over the surplus"
        effective = {**current, **{a.entity_ref: a.centavos for a in named}}
        assert sum(effective.values()) <= _surplus(state), move
    pool = pool_of(state)
    for wanted in q.expect.states:
        checked = check_text("reply", "expected", wanted, pool)
        assert checked.numbers, wanted
        assert checked.ok, f"{q.id}: {wanted} isn't a figure or fact then"
    figures = {refs.figure(f) for f in state.run.figures}
    for ref in q.expect.cites:
        assert ref in figures, f"{q.id}: no figure {ref}"
    facts = {f"fact:{refs.fact(f)}" for f in state.snapshot.facts}
    for source in q.expect.sources:
        assert source in ("said", "memory", "doc") or source in facts, f"{q.id}: {source}"


def _surplus(state: TurnState) -> int:
    value = state.run.get("cashflow.monthly_surplus").value
    assert isinstance(value, int)
    return value


def test_a_broken_set_names_the_question_and_the_field(tmp_path: Path) -> None:
    good = (
        'version = 1\n[[question]]\nid = "q01"\non = 2026-09-15\n'
        "known_at = 2026-09-15T09:00:00+08:00\n"
        'message = "Hi"\nwhy = "A test."\n'
    )
    path = tmp_path / "q.toml"
    for extra, error in [
        ('[question.expect]\nstates = "₱1.00"\n', "q01: expect.states must be a list"),
        ("[question.expect]\noptions = { min = 3, max = 1 }\n", "q01: expect.options"),
        ('[question.expect]\nallocations = [{ card = "₱1.00" }]\n', "isn't an entity ref"),
        ('[question.expect]\nallocations = [{ "debt:card" = "1000" }]\n', "written as ₱4,000.00"),
        ('[question.expect]\nsources = ["the brief"]\n', "isn't one"),
        ('[question.expect]\nstates = ["₱1.00 or ₱2.00"]\n', "'₱1.00 or ₱2.00' must be one figure"),
        ('[question.expect]\nstates = ["₱1.00 | soon"]\n', "'soon' must be one figure"),
        ('[question.expect]\nrecommended = "A"\n', 'can only be "none"'),
        ("[question.expect]\nscore = 1\n", "unknown expectations"),
        ("tone = 1\n", "unknown fields"),
    ]:
        path.write_text(good + extra, encoding="utf-8")
        with pytest.raises(TestSetError, match=error):
            read_test_set(path)
    path.write_text(good.replace("+08:00", ""), encoding="utf-8")
    with pytest.raises(TestSetError, match="q01: known_at must be a time with its zone"):
        read_test_set(path)
    path.write_text(good + good.partition("\n")[2], encoding="utf-8")
    with pytest.raises(TestSetError, match="two questions share an id"):
        read_test_set(path)


async def _session_2(house: Villanueva, make_settings: MakeSettings) -> tuple[TurnAnswer, Any]:
    q = BY_ID["q01"]
    manager, _ = _manager(make_settings, _scripted(_session_2_script(), q.seed))
    state = _state(house, q)
    answer = await answer_turn(manager, manager.turn(q.seed), state)
    return answer, state


def _scripted(script: dict[str, Any], seed: str) -> dict[str, Any]:
    """A script recorded under session 2's seed, keyed for another turn's seed."""
    return {f"{seed}/{key.partition('/')[2]}": reply for key, reply in script.items()}


async def test_session_2_scores_every_check(house: Villanueva, make_settings: MakeSettings) -> None:
    answer, state = await _session_2(house, make_settings)
    result = score(BY_ID["q01"], answer, state)
    assert [(c.name, c.passed) for c in result.checks] == [
        ("answered", True),
        ("numbers", True),
        ("states 9 months", True),
        ("states 17 months", True),
        ("2 to 4 options", True),
        ("offers account:emergency-fund ₱0.00, debt:credit-card ₱9,050.00", True),
        ("offers account:emergency-fund ₱5,050.00, debt:credit-card ₱4,000.00", True),
        ("leaves the choice", True),
        (f"cites {CARD_PAYOFF}", True),
        ("cites said", True),
    ]
    assert result.value == 1.0


async def test_a_worse_answer_scores_lower(house: Villanueva, make_settings: MakeSettings) -> None:
    answer, state = await _session_2(house, make_settings)
    q = BY_ID["q01"]
    a, _ = answer.options
    # It recommends A, drops B, and states a number the check flagged.
    flagged = TextCheck("reply", "the reply", "₱8,000", (Number("₱8,000", "money", None),))
    worse = replace(answer, options=(a,), recommended=a.label, checks=(flagged, *answer.checks[1:]))
    result = score(q, worse, state)
    failed = {c.name: c.detail for c in result.checks if not c.passed}
    assert failed == {
        "numbers": "₱8,000",
        "states 17 months": "",
        "2 to 4 options": "1 options",
        "offers account:emergency-fund ₱5,050.00, debt:credit-card ₱4,000.00": "",
        "leaves the choice": a.label,
        "cites said": "",
    }
    assert result.value == pytest.approx(4 / 10)
    # A failed turn scores 0, whatever else.
    assert score(q, None, None).value == 0.0
    # Rounded and differently written numbers state the same figure; a wrong one doesn't.
    reply = replace(answer, options=(), reply="About 9.0 months, or ₱12,460.1 in interest.")
    assert [c.passed for c in score(q, reply, state).checks[2:4]] == [True, False]
    # Either form of a figure states it: a payoff as a duration or as a date.
    either = replace(q, expect=replace(q.expect, states=("9 months | Jun 15, 2027",)))
    dated = replace(answer, options=(), reply="The card is paid off by Jun 15, 2027.")
    (named,) = [c for c in score(either, dated, state).checks if c.name.startswith("states")]
    assert (named.name, named.passed) == ("states 9 months or Jun 15, 2027", True)
    assert not score(either, replace(dated, reply="By Jul 15, 2027."), state).checks[2].passed
    years = replace(answer, options=(), reply="That takes 1.5 years.")
    q_17 = replace(q, expect=replace(q.expect, states=("18 months",)))
    assert score(q_17, years, state).checks[2].passed


async def test_not_recommended_and_sources(house: Villanueva, make_settings: MakeSettings) -> None:
    answer, state = await _session_2(house, make_settings)
    a, b = answer.options
    q = replace(
        BY_ID["q10"],
        expect=replace(
            BY_ID["q10"].expect,
            states=(),
            not_recommended={"debt:credit-card": "₱9,050.00", "account:emergency-fund": "₱0.00"},
            sources=("fact:preference.debt_strategy", "said", "doc"),
        ),
    )
    names = {c.name: c.passed for c in score(q, replace(answer, recommended=b.label), state).checks}
    assert names["doesn't recommend account:emergency-fund ₱0.00, debt:credit-card ₱9,050.00"]
    assert names["cites fact:preference.debt_strategy"]
    assert names["cites said"]
    assert not names["cites doc"]
    bad = score(q, replace(answer, recommended=a.label), state).checks
    assert not next(c for c in bad if c.name.startswith("doesn't recommend")).passed


async def test_the_single_agent_answers_alone_with_the_same_checks(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    """The baseline: one agent on the strong deployment runs its own what-ifs and hands in the same
    checked answer, naming no specialist; it scores on the same set."""
    q = BY_ID["q01"]
    script = {
        f"{q.seed}/orchestrator/1": calls(
            ("run_what_if", {"allocations": ALL_ON_CARD}),
            ("run_what_if", {"allocations": SPLIT}),
        ),
        f"{q.seed}/orchestrator/2": calls(
            (
                "submit_answer",
                {
                    "reply": "Mara wants the card gone, Jun wants cash on hand: two ways to go.",
                    "options": [
                        {
                            "label": "A: all extra on the card",
                            "what_if": "orch-W1",
                            "summary": "Card paid off in 9 months, ₱12,460.10 of interest.",
                            "sources": [f"figure:orch-W1:{CARD_PAYOFF}", "said"],
                            "specialists": [],
                        },
                        {
                            "label": "B: split",
                            "what_if": "orch-W2",
                            "summary": "Card paid off in 17 months, ₱24,303.62 of interest.",
                            "sources": [
                                f"figure:orch-W2:{CARD_PAYOFF}",
                                f"figure:orch-W2:{CARD_INTEREST}",
                                "said",
                            ],
                            "specialists": [],
                        },
                    ],
                    "recommended": "",
                    "resolution": None,
                },
            )
        ),
    }
    manager, backend = _manager(make_settings, script)
    state = _state(house, q)
    answer = await answer_alone(manager, manager.turn(q.seed), state)
    assert [o.specialists for o in answer.options] == [(), ()]
    assert answer.proposals == ()
    assert answer.resolution is None
    assert score(q, answer, state).value == 1.0
    # One agent, the strong tier, the single role last in its prompt, and its own Meko search.
    (key, deployment, request), *_ = backend.requests
    assert (key, deployment) == (f"{q.seed}/orchestrator/1", "kako-strong")
    assert "Kako's planner, working alone" in request.messages[0].content
    assert {t.name for t in request.tools} == {
        "get_figures",
        "get_facts",
        "get_decisions",
        "read_turns",
        "get_history",
        "get_figures_on",
        "read_document",
        "calculate",
        "search_memory",
        "run_what_if",
        "propose_change",
        "submit_answer",
    }


def test_the_command_replays_unless_asked_to_record(make_settings: MakeSettings) -> None:
    """A whole run on Foundry costs money: `kako test-set` replays its recording even in live mode
    (the default), and only KAKO_MODEL_MODE=record calls the model."""
    from kako.cli import settings_for_test_set

    recorded = TEST_SET.parent.parent / "recorded"
    for mode, expected in [("live", "replay"), ("replay", "replay"), ("record", "record")]:
        settings = settings_for_test_set(make_settings(model_mode=mode), "single")
        assert settings.model_mode == expected
        assert settings.recorded_responses == recorded / "test-set-single.json"
    mine = Path("elsewhere.json")
    chosen = make_settings(model_mode="replay", recorded_responses=mine)
    assert settings_for_test_set(chosen, "specialists").recorded_responses == mine
