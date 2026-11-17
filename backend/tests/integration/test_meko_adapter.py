"""The Meko adapter on local Meko, with every call counted in Postgres (`meko_call`).

Phase 2, task 6, done when: the adapter's integration tests pass against local Meko in CI. Each
test cleans up what it wrote. Never run against Meko Cloud: the fixture refuses it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.db.meko_log import DbCallLog
from kako.demo.files import read_demo
from kako.demo.kb import AGENT as SEED
from kako.demo.kb import upload_demo_documents
from kako.meko.adapter import Turn
from kako.meko.client import MekoMcpSession
from kako.meko.mcp import open_meko
from kako.meko.quota import MekoQuotaError
from tests.conftest import MakeSettings

pytestmark = pytest.mark.integration

AGENT = "kako:ci-adapter"


async def _calls(engine: AsyncEngine) -> list[tuple[str, str, str, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT target, tool, agent_id, outcome FROM meko_call ORDER BY created_at")
        )
        return [tuple(r) for r in rows]  # type: ignore[misc]


async def test_the_adapter_on_local_meko(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    run = uuid.uuid4().hex[:12]
    settings = make_settings(meko_mcp_url=test_meko_url)
    async with open_meko(settings, DbCallLog(migrated), max_calls=14) as meko:
        conversation = await meko.create_conversation(
            agent_id=AGENT, title=f"CI adapter {run}", session_key=f"ci-adapter-{run}"
        )
        try:
            turn = Turn(
                input=f"Run {run}: the Testhouse rent is 18,000 pesos a month.",
                output="Noted: rent of 18,000 pesos a month, a fixed cost.",
                plan=("Read the stated rent", "Record it as a fixed monthly cost"),
                reasoning="Rent is a fixed cost.",
                metadata={"kako_turn": 1},
                seed=f"{run}:1",
            )
            assert await meko.add_turn(conversation, turn, agent_id=AGENT)
            sentence = f"Testhouse {run}'s emergency fund target is three months of essentials."
            memory_id = await meko.add_memory(
                conversation, sentence, {"kako_source": "approved_fact"}, agent_id=AGENT
            )
            try:
                found = await meko.search_context(
                    conversation, f"Testhouse {run} emergency fund target", agent_id=AGENT, limit=3
                )
                assert found.memories[0].id == memory_id
                assert found.memories[0].text == sentence
                assert found.memories[0].metadata["kako_source"] == "approved_fact"
                await meko.update_memory(
                    conversation, memory_id, f"Until Nov 30, {sentence}", agent_id=AGENT
                )
            finally:
                await meko.delete_memory(conversation, memory_id, agent_id=AGENT)
        finally:
            await meko.delete_conversation(conversation, agent_id=AGENT)

    calls = await _calls(migrated)
    assert [c[1] for c in calls] == [
        "conversation_create",
        "conversation_add_message",
        "memory_add",
        "context_search",
        "memory_update",
        "memory_delete_by_id",
        "conversation_delete",
    ]
    assert {(c[0], c[2], c[3]) for c in calls} == {("local", AGENT, "ok")}
    async with migrated.connect() as conn:
        search = await conn.execute(
            text("SELECT latency_ms, result_count FROM meko_call WHERE tool = 'context_search'")
        )
        latency, results = search.one()
        assert latency >= 0
        assert results >= 1


@asynccontextmanager
async def throwaway_datapack(url: str) -> AsyncIterator[str]:
    """A datapack of its own for a test that uploads files, deleted afterwards with all it holds:
    Meko's document status names no document id, so files can't be deleted one by one."""
    async with (
        httpx.AsyncClient(timeout=60) as http,
        MekoMcpSession(http, url, max_tool_calls=4) as session,
    ):
        conversation = (
            await session.call_tool("conversation_create", {"agent_id": AGENT, "title": "CI kb"})
        )["id"]
        created = await session.call_tool(
            "datapack_create",
            {"conversation_id": conversation, "name": f"kako-ci-{uuid.uuid4().hex[:12]}"},
        )
        datapack_id = created.get("datapack_id") or created["id"]
        try:
            yield datapack_id
        finally:
            await session.call_tool(
                "datapack_delete", {"conversation_id": conversation, "datapack_id": datapack_id}
            )
            await session.call_tool(
                "conversation_delete", {"agent_id": AGENT, "conversation_id": conversation}
            )


async def test_the_demo_documents_on_local_meko(
    migrated: AsyncEngine, test_meko_url: str, make_settings: MakeSettings
) -> None:
    demo = read_demo()
    async with throwaway_datapack(test_meko_url) as datapack_id:
        settings = make_settings(meko_mcp_url=test_meko_url, meko_datapack_id=datapack_id)
        bound = 2 + len(demo.documents) * 11
        async with open_meko(settings, DbCallLog(migrated), max_calls=bound) as meko:
            conversation = await meko.create_conversation(agent_id=SEED, title="CI kb")
            documents = await upload_demo_documents(meko, demo, conversation, checks=10)
            assert [d.filename for d in documents] == [p.name for p in demo.documents]
            assert all(d.state == "completed" for d in documents)
            assert not any(d.already_uploaded for d in documents)
            hits = await meko.search_knowledge(
                conversation, "When is 13th-month pay paid?", agent_id=SEED
            )
            assert "13th-month" in hits[0].text
    tools = [c[1] for c in await _calls(migrated)]
    assert tools.count("knowledgebase_upload_document") == len(demo.documents)


async def test_the_counter_in_postgres_refuses_past_the_ceiling(migrated: AsyncEngine) -> None:
    """On Meko Cloud's ceiling, reserved straight on the log: nothing here reaches any Meko."""
    log = DbCallLog(migrated)
    await log.reserve("cloud", "context_search", "kako:orchestrator", 2)
    await log.reserve("cloud", "selflearning_verify", "kako:orchestrator", 2)
    with pytest.raises(MekoQuotaError):
        await log.reserve("cloud", "context_search", "kako:orchestrator", 2)
    # Local calls and other allowances don't count against it.
    await log.reserve("local", "context_search", "kako:orchestrator", None)
    await log.reserve("cloud", "memory_search", "kako:orchestrator", 2)
    assert await log.used("cloud") == {
        "context_search": 1,
        "selflearning_verify": 1,
        "memory_search": 1,
    }
    outcomes = [c[3] for c in await _calls(migrated) if c[1] == "context_search"]
    assert sorted(outcomes) == ["ok", "ok", "refused"]


async def test_two_callers_cannot_both_take_the_last_call(migrated: AsyncEngine) -> None:
    log = DbCallLog(migrated)

    async def reserve() -> bool:
        try:
            await log.reserve("cloud", "memory_add", "kako:dreaming", 3)
        except MekoQuotaError:
            return False
        return True

    taken = await asyncio.gather(*(reserve() for _ in range(8)))
    assert sum(taken) == 3
    assert (await log.used("cloud"))["memory_add"] == 3


async def test_the_upload_command(
    migrated: AsyncEngine,
    test_database_url: str,
    test_meko_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`kako demo upload` twice: the second run finds every file already there."""
    from kako.cli import main
    from kako.settings import get_settings

    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    monkeypatch.setenv("MEKO_MCP_URL", test_meko_url)
    demo = read_demo()
    async with throwaway_datapack(test_meko_url) as datapack_id:
        monkeypatch.setenv("KAKO_MEKO_DATAPACK_ID", datapack_id)
        get_settings.cache_clear()
        try:
            assert await asyncio.to_thread(main, ["demo", "upload"]) == 0
            assert await asyncio.to_thread(main, ["demo", "upload"]) == 0
        finally:
            get_settings.cache_clear()
    out = capsys.readouterr().out.splitlines()
    searchable = f"{len(demo.documents)} documents searchable in Meko (local)"
    assert out == [f"{searchable}; {len(demo.documents)} new.", f"{searchable}; 0 new."]
    assert all(c[0] == "local" for c in await _calls(migrated))
