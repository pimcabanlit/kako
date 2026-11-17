"""CI's smoke test against local Meko: create a conversation, add a memory, find it.

It cleans up after itself (the memory and the conversation are deleted), uses a fresh session id
per run, and is capped at 6 tool calls. Never run against Meko Cloud: the fixture refuses it.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from kako.meko.client import MekoMcpSession

pytestmark = pytest.mark.integration

AGENT = "kako:ci-smoke"


async def test_conversation_memory_round_trip(test_meko_url: str) -> None:
    run = uuid.uuid4().hex[:12]
    fact = f"Smoke test {run}: the Testhouse household keeps a three-month emergency fund."
    async with (
        httpx.AsyncClient(timeout=30) as http,
        MekoMcpSession(http, test_meko_url, max_tool_calls=6) as meko,
    ):
        conversation = await meko.call_tool(
            "conversation_create",
            {"agent_id": AGENT, "session_id": f"ci-smoke-{run}", "title": f"CI smoke {run}"},
        )
        conversation_id = conversation["id"]
        try:
            added = await meko.call_tool(
                "memory_add",
                {"agent_id": AGENT, "conversation_id": conversation_id, "text": fact},
            )
            memory_id = added["results"][0]["id"]

            found = await meko.call_tool(
                "memory_search",
                {
                    "agent_id": AGENT,
                    "conversation_id": conversation_id,
                    "query": f"How big is the Testhouse emergency fund? ({run})",
                    "run_id": conversation_id,
                    "limit": 3,
                },
            )
            assert [m["id"] for m in found["results"]][:1] == [memory_id]
            assert found["results"][0]["memory"] == fact

            await meko.call_tool(
                "memory_delete_by_id",
                {"agent_id": AGENT, "conversation_id": conversation_id, "memory_id": memory_id},
            )
        finally:
            await meko.call_tool(
                "conversation_delete", {"agent_id": AGENT, "conversation_id": conversation_id}
            )
        assert sum(meko.tool_calls.values()) == 5
