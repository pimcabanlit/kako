"""The brief gathered from Postgres (the demo household, loaded through the fact store) and local
Meko, with its one `context_search` counted in `meko_call`.

Phase 3, task 2, done when: the brief for the worked example is under budget and contains the
promoted preference (until Phase 4, the approved preference from the fact store; Pim, Nov 24).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.brief_store import BriefStoreError, gather_brief
from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.meko.mcp import open_meko
from tests.conftest import MakeSettings

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
DEC_1 = date(2026, 12, 1)
AGENT = "kako:ci-brief"


async def _demo(engine: AsyncEngine) -> uuid.UUID:
    async with engine.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 12, 1, 12, tzinfo=MANILA)
        )
        await conn.commit()
    return household_id


async def test_the_worked_examples_brief_from_postgres_and_local_meko(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    household_id = await _demo(migrated)
    run = uuid.uuid4().hex[:12]
    settings = make_settings(meko_mcp_url=test_meko_url)
    sentence = (
        f"Mara Villanueva ({run}) said the family keeps cash on hand because Lia starts school."
    )
    async with open_meko(settings, DbCallLog(migrated), max_calls=8) as meko:
        conversation = await meko.create_conversation(agent_id=AGENT, title=f"CI brief {run}")
        try:
            memory_id = await meko.add_memory(
                conversation, sentence, {"kako_source": "approved_fact"}, agent_id=AGENT
            )
            try:
                async with migrated.connect() as conn:
                    brief, figures = await gather_brief(
                        conn,
                        meko,
                        household_id=household_id,
                        on=DEC_1,
                        known_at=datetime(2026, 12, 1, 6, tzinfo=UTC),
                        message=f"Mara Villanueva ({run}): why do we keep cash on hand?",
                        conversation_id=conversation,
                        budget=settings.brief_token_budget,
                        search_limit=settings.brief_search_limit,
                    )
            finally:
                await meko.delete_memory(conversation, memory_id, agent_id=AGENT)
        finally:
            await meko.delete_conversation(conversation, agent_id=AGENT)

    assert brief.tokens <= 3_000
    assert (
        "- preference.debt_vs_flexibility = flexibility (since Oct 20, 2026); proposed by "
        "dreaming, approved by Mara on Oct 20, 2026"
    ) in brief.text
    assert "- cashflow.monthly_surplus = ₱25,050.00:" in brief.text
    assert figures.value("cashflow.monthly_surplus") == 2_505_000
    assert memory_id in brief.memories.values()
    assert sentence in brief.text
    async with migrated.connect() as conn:
        searches = await conn.execute(
            text("SELECT agent_id, outcome FROM meko_call WHERE tool = 'context_search'")
        )
        assert [tuple(r) for r in searches] == [("kako:orchestrator", "ok")]  # one search


async def test_no_message_means_no_search(migrated: AsyncEngine) -> None:
    household_id = await _demo(migrated)
    async with migrated.connect() as conn:
        brief, _ = await gather_brief(
            conn,
            None,
            household_id=household_id,
            on=DEC_1,
            known_at=None,
            message="",
            conversation_id=None,
            budget=3_000,
        )
        with pytest.raises(BriefStoreError, match="doesn't exist"):
            await gather_brief(
                conn,
                None,
                household_id=uuid.uuid4(),
                on=DEC_1,
                known_at=None,
                message="",
                conversation_id=None,
                budget=3_000,
            )
    assert "No search was made." in brief.text
    assert "Active decisions (cite as decision:<ref>)\nNone." in brief.text
