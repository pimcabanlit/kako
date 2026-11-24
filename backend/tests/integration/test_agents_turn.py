"""Session 2 end to end on local services: the demo household in Postgres, the brief's search and a
specialist's extra search on local Meko, every step and model call logged in Postgres. The model is
scripted (no Azure), so the run is the same every time.

Phase 3, task 3: the done-when test (options A and B with the worked example's figures, cited)
on the real stores, and the run on local Meko that REVIEW.md asks of an agent change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.brief_store import gather_brief
from kako.agents.model_manager import ModelManager
from kako.agents.orchestrator import answer_turn
from kako.agents.tools import TurnState
from kako.db.agent_steps import DbStepLog
from kako.db.llm_log import DbLlmLog
from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.meko.mcp import open_meko
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend, calls
from tests.support.villanueva import SEP_15
from tests.test_agents_turn import ALL_ON_CARD, CARD_PAYOFF, SEED, SESSION_2, SPLIT
from tests.test_agents_turn import _session_2_script as script

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
AGENT = "kako:ci-turn"


async def _household(engine: AsyncEngine, conversation: str) -> tuple[uuid.UUID, uuid.UUID]:
    """The demo household as it stood on the morning of Sep 15 (before plan v2), and a session."""
    async with engine.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 9, 15, 9, tzinfo=MANILA)
        )
        session_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO session (id, household_id, meko_conversation_id, title, "
                "household_date, started_at) VALUES (:id, :h, :c, 'Session 2', :d, :t)"
            ),
            {
                "id": session_id,
                "h": household_id,
                "c": conversation,
                "d": SEP_15,
                "t": datetime(2026, 9, 15, 1, tzinfo=UTC),
            },
        )
        await conn.commit()
    return household_id, session_id


async def test_session_2_on_postgres_and_local_meko(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    settings = make_settings(
        meko_mcp_url=test_meko_url, model_strong="kako-strong", model_fast="kako-fast"
    )
    turn_script = script()
    # The debt specialist also makes its one extra search, on local Meko.
    turn_script[f"{SEED}/debt#1/1"] = calls(
        ("run_what_if", {"allocations": ALL_ON_CARD}),
        ("run_what_if", {"allocations": SPLIT}),
        ("search_memory", {"query": "credit card interest and paying it down"}),
    )
    async with open_meko(settings, DbCallLog(migrated), max_calls=8) as meko:
        conversation = await meko.create_conversation(
            agent_id=AGENT, title=f"CI turn {uuid.uuid4().hex[:8]}"
        )
        try:
            household_id, session_id = await _household(migrated, conversation)
            async with migrated.connect() as conn:
                brief, inputs = await gather_brief(
                    conn,
                    meko,
                    household_id=household_id,
                    on=SEP_15,
                    known_at=None,
                    message=SESSION_2,
                    conversation_id=conversation,
                    budget=settings.brief_token_budget,
                )
            state = TurnState(brief, inputs, SEED, meko, conversation)
            manager = ModelManager(settings, ScriptedBackend(turn_script), DbLlmLog(migrated))
            turn = manager.turn(SEED, session_id=session_id, steps=DbStepLog(migrated, session_id))
            answer = await answer_turn(manager, turn, state)
        finally:
            await meko.delete_conversation(conversation, agent_id=AGENT)

    assert brief.tokens <= settings.brief_token_budget
    assert inputs.run.value("cashflow.monthly_surplus") == 905_000
    a, b = answer.options
    assert a.label == "A: all extra on the card"
    assert {x.centavos for x in a.allocations} == {905_000, 0}
    assert {c.ref: c.shown for c in a.citations if c.figure is not None} == {
        f"figure:debt1-W1:{CARD_PAYOFF}": "9 months",
        "figure:debt1-W1:debt.total_interest@debt:credit-card": "₱12,460.10",
    }
    assert {(x.centavos, x.spec) for x in b.allocations} == {
        (400_000, "said:4000"),
        (505_000, "rest"),
    }
    assert {c.ref: c.shown for c in b.citations if c.figure is not None} == {
        f"figure:savings1-W1:{CARD_PAYOFF}": "17 months",
        "figure:savings1-W1:debt.total_interest@debt:credit-card": "₱24,303.62",
        "figure:savings1-W1:savings.months_to_target": "12 months",
    }

    async with migrated.connect() as conn:
        searches = list(
            await conn.execute(
                text(
                    "SELECT agent_id, outcome FROM meko_call "
                    "WHERE tool = 'context_search' ORDER BY id"
                )
            )
        )
        steps = list(
            await conn.execute(
                text(
                    "SELECT agent, tool, outcome FROM agent_step WHERE session_id = :s ORDER BY seq"
                ),
                {"s": session_id},
            )
        )
        model_calls = (
            await conn.execute(
                text("SELECT count(*) FROM llm_call WHERE meko_turn_seed = :seed"), {"seed": SEED}
            )
        ).scalar_one()
    # One search for the brief, one extra by the debt specialist: both counted.
    assert sorted(tuple(r) for r in searches) == [("kako:debt", "ok"), ("kako:orchestrator", "ok")]
    assert ("debt", "search_memory", "ok") in [tuple(r) for r in steps]
    assert len(steps) == 9
    assert model_calls == 6
