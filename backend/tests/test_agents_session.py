"""What a turn sends to Meko as its trace, and which stored row each final number check is about.
Session 2 with a scripted model; no database, no Meko."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from kako.agents.ask import Started, trace_turn
from kako.agents.checks import Number, TextCheck
from kako.agents.orchestrator import answer_turn
from kako.db.plan_store import SavedAnswer
from tests.conftest import MakeSettings
from tests.support.villanueva import SEP_15, Villanueva, build
from tests.test_agents_turn import SEED, SESSION_2, _manager, _session_2_script, _state


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


async def test_the_trace_has_the_steps_the_reasons_and_the_ids(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    manager, _ = _manager(make_settings, _session_2_script())
    state = _state(house)
    answer = await answer_turn(manager, manager.turn(SEED), state)
    plan, a1, a2, b1, b2, rec = (uuid.uuid4() for _ in range(6))
    saved = SavedAnswer(
        plan, 3, {"A: all extra on the card": (a1, a2), "B: split": (b1, b2)}, (rec,)
    )
    state.stored["debt1-W1"] = run = uuid.uuid4()
    session = Started(uuid.uuid4(), uuid.uuid4(), "c1", "Session 2", SEP_15)
    calc = uuid.uuid4()
    turn = trace_turn(SESSION_2, answer, saved, state, calc, session, SEED)

    assert turn.input == SESSION_2
    assert turn.output == answer.reply
    assert turn.seed == f"{session.session_id.hex}:{SEED}"  # unique across conversations
    assert turn.plan == (
        "Read the brief: the household's figures, facts, decisions and Meko's context",
        "Asked the debt and savings specialists",
        "Reconciled their proposals in code (over-allocation) and left the choice to the household",
        "Offered 2 options, none recommended",
    )
    assert (turn.reasoning or "").startswith("debt specialist: ")
    assert "\n\nReconciliation: " in (turn.reasoning or "")
    assert turn.metadata == {
        "kako_turn": SEED,
        "kako_session_id": str(session.session_id),
        "kako_household_id": str(session.household_id),
        "kako_household_date": "2026-09-15",
        "kako_calc_run_id": str(calc),
        "kako_what_if_runs": {"debt1-W1": str(run)},
        "kako_plan_id": str(plan),
        "kako_plan_version": 3,
        "kako_recommendation_ids": {
            "A: all extra on the card": [str(a1), str(a2)],
            "B: split": [str(b1), str(b2)],
        },
        "kako_reconciliation_ids": [str(rec)],
    }

    # Each final check names what it checked: the plan, an option's first row, the conflict.
    by_label = {c.label: saved.subject_id(c) for c in answer.checks}
    assert by_label == {
        "the reply": plan,
        "option 'A: all extra on the card''s label": a1,
        "option 'A: all extra on the card''s summary": a1,
        "option 'B: split''s label": b1,
        "option 'B: split''s summary": b1,
        "the resolution's reason": rec,
    }
    nothing = SavedAnswer(None, None)
    assert {nothing.subject_id(c) for c in answer.checks} == {None}


async def test_numbers_flagged_in_a_text_are_marked_in_meko(
    house: Villanueva, make_settings: MakeSettings
) -> None:
    """Meko keeps the texts as shown, flagged numbers and all: the metadata names them, so the trace
    (and Meko's own extraction) can tell which numbers nothing backs."""
    manager, _ = _manager(make_settings, _session_2_script())
    state = _state(house)
    answer = await answer_turn(manager, manager.turn(SEED), state)
    session = Started(uuid.uuid4(), uuid.uuid4(), "c1", "Session 2", SEP_15)
    clean = trace_turn(
        SESSION_2, answer, SavedAnswer(None, None), state, uuid.uuid4(), session, SEED
    )
    assert "kako_flagged" not in clean.metadata
    wrong = TextCheck("reply", "the reply", "₱9,999.00", (Number("₱9,999.00", "money", None),))
    flagged = replace(answer, checks=(wrong, *answer.checks[1:]))
    turn = trace_turn(
        SESSION_2, flagged, SavedAnswer(None, None), state, uuid.uuid4(), session, SEED
    )
    assert turn.metadata["kako_flagged"] == {"the reply": ["₱9,999.00"]}
