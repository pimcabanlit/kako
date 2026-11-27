"""The model call log and the agents' steps in Postgres: `llm_call` and `agent_step` rows, the daily
spend read back from them, and a recorded turn's calls and steps written as it runs."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.chat import ToolSpec
from kako.agents.model_manager import ModelManager, SpendRefused
from kako.agents.prompt_registry import SystemPrompt, load_prompt
from kako.agents.spend import LlmCallRecord
from kako.agents.tool_loop import Tool, ToolResult, run_agent
from kako.agents.turn import StepRecord
from kako.db.agent_steps import AGENT_STEP, DbStepLog
from kako.db.llm_log import LLM_CALL, DbLlmLog
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend, calls, says

pytestmark = pytest.mark.integration
NOW = datetime.now(UTC)
OBJECT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


async def _session(engine: AsyncEngine) -> uuid.UUID:
    household, session = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO household (id, name, currency, timezone, as_of_date, created_at) "
                "VALUES (:id, 'Loghouse household', 'PHP', 'Asia/Manila', :d, :t)"
            ),
            {"id": household, "d": date(2026, 9, 15), "t": NOW},
        )
        await conn.execute(
            text(
                "INSERT INTO session (id, household_id, meko_conversation_id, title, "
                "household_date, started_at) VALUES (:id, :h, :c, 'Session 2', :d, :t)"
            ),
            {
                "id": session,
                "h": household,
                "c": f"conv-{session}",
                "d": date(2026, 9, 15),
                "t": NOW,
            },
        )
    return session


def _record(cost: str, *, at: datetime, replay: bool = False) -> LlmCallRecord:
    return LlmCallRecord(
        None,
        None,
        "system",
        "kako-fast",
        10,
        2,
        0,
        50,
        Decimal(cost),
        "ok",
        replay,
        created_at=at,
    )


async def test_the_daily_spend_reads_real_calls_since_the_day_began(migrated: AsyncEngine) -> None:
    log = DbLlmLog(migrated)
    day = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    for record in (
        _record("0.001250", at=day + timedelta(minutes=1)),
        _record("0.002000", at=day + timedelta(minutes=2)),
        _record("5.000000", at=day + timedelta(minutes=3), replay=True),
        _record("7.000000", at=day - timedelta(minutes=1)),  # yesterday
    ):
        await log.write(record)
    assert await log.spent_since(day) == Decimal("0.003250")
    assert await log.spent_since(day + timedelta(days=1)) == Decimal(0)


async def test_a_turn_writes_its_calls_and_steps(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    session = await _session(migrated)
    seed = "session-2:turn-1"
    run_id = None  # no what-if in this turn

    async def get_figures(_: dict[str, Any]) -> ToolResult:
        return ToolResult('{"F1": "₱9,050.00"}', "1 figure: the surplus", calc_run_id=run_id)

    backend = ScriptedBackend(
        {
            f"{seed}/debt#1/1": calls(("get_figures", {})),
            f"{seed}/debt#1/2": says("Option A.", tokens=(1_000, 50)),
        }
    )
    models = ModelManager(
        make_settings(model_fast="kako-fast", daily_spend_cap_usd="1"), backend, DbLlmLog(migrated)
    )
    turn = models.turn(seed, session_id=session, steps=DbStepLog(migrated, session))
    result = await run_agent(
        models,
        turn,
        agent="debt",
        path="debt#1",
        tier="fast",
        system=SystemPrompt("s", (load_prompt("common").version, load_prompt("debt").version)),
        user="u",
        tools=[Tool(ToolSpec("get_figures", "Read.", OBJECT), get_figures)],
        max_output_tokens=500,
    )
    assert result.text == "Option A."

    async with migrated.connect() as conn:
        llm = (await conn.execute(select(LLM_CALL).order_by(LLM_CALL.c.created_at))).mappings()
        rows = [dict(r) for r in llm]
        steps = [dict(r) for r in (await conn.execute(select(AGENT_STEP))).mappings()]
    assert [(r["agent"], r["outcome"], r["session_id"], r["meko_turn_seed"]) for r in rows] == [
        ("debt", "ok", session, seed),
        ("debt", "ok", session, seed),
    ]
    assert rows[1]["cost_usd"] == Decimal("0.000125")  # 1,000 x 0.10 + 50 x 0.50 per million
    # Each call names the prompts it ran with, by name, with the SHA-256 of each text.
    assert [r["prompts"] for r in rows] == [
        {
            "common": {"source": "repo", "sha256": load_prompt("common").version.sha256},
            "debt": {"source": "repo", "sha256": load_prompt("debt").version.sha256},
        }
    ] * 2
    assert [(s["seq"], s["agent"], s["tool"], s["outcome"]) for s in steps] == [
        (1, "debt", "get_figures", "ok")
    ]
    assert steps[0]["result_summary"] == "1 figure: the surplus"


async def test_a_refused_call_is_logged(migrated: AsyncEngine, make_settings: MakeSettings) -> None:
    log = DbLlmLog(migrated)
    await log.write(_record("0.999000", at=datetime.now(UTC)))
    models = ModelManager(
        # gpt-5-mini's output price: at Haiku's, 1,000 tokens would still fit under the cap.
        make_settings(model_fast="kako-fast", daily_spend_cap_usd="1", price_fast_output="2.00"),
        ScriptedBackend({"t/x/1": says("never")}),
        log,
    )
    with pytest.raises(SpendRefused):
        await run_agent(
            models,
            models.turn("t"),
            agent="budget",
            path="x",
            tier="fast",
            system=SystemPrompt("s"),
            user="u",
            tools=[],
            max_output_tokens=1_000,
        )
    async with migrated.connect() as conn:
        outcomes = (await conn.execute(select(LLM_CALL.c.outcome))).scalars().all()
    assert sorted(outcomes) == ["budget_exceeded", "ok"]


async def test_a_step_log_keeps_to_its_session(migrated: AsyncEngine) -> None:
    session = await _session(migrated)
    log = DbStepLog(migrated, session)
    step = StepRecord(uuid.uuid4(), "t", "debt", 1, "get_figures", "{}", "ok", None, "ok")
    with pytest.raises(ValueError, match="this log's session"):
        await log.write(step)
