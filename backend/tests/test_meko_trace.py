"""A session's trace on local Meko: its calls read out of Meko's call log, a page at a time, as
spans. The call log is served by a mock; the integration test reads the real one."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from kako.meko.client import MekoError, MekoProtocolError
from kako.meko.trace import MAX_PAGES, calls_url, local_trace
from tests.conftest import MakeSettings

SINCE = datetime(2026, 11, 24, 8, tzinfo=UTC)


def _call(
    n: int, conversation: str, at: str = "2026-11-24T08:09:55.1Z", **kw: Any
) -> dict[str, Any]:
    return {
        "id": n,
        "at": at,
        "tool": kw.get("tool", "context_search"),
        "agent_id": "kako:orchestrator",
        "conversation_id": conversation,
        "ms": 12,
        "ok": True,
        "error_code": "",
        "steps": kw.get("steps", []),
    }


def _log(pages: list[list[dict[str, Any]]], seen: list[httpx.Request]) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        n = len(seen) - 1
        more = n + 1 < len(pages)
        return httpx.Response(200, json={"data": {"calls": pages[n], "more": more}})

    return httpx.MockTransport(answer)


async def test_the_conversations_calls_oldest_first(make_settings: MakeSettings) -> None:
    settings = make_settings(meko_mcp_url="http://127.0.0.1:7777/mcp")
    pages = [
        [
            _call(9, "c1", tool="conversation_add_message"),
            _call(8, "other"),
            _call(7, "c1", steps=[{"step": "memory_search", "ms": 5, "n": 2}]),
        ],
        [
            _call(6, "c1", tool="conversation_create"),
            _call(5, "c1", at="2026-11-24T07:59:59Z"),  # before the session: never read on
            _call(4, "c1"),
        ],
    ]
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_log(pages, seen)) as http:
        spans = await local_trace(http, settings, "c1", since=SINCE)
    assert [(s.call_id, s.tool) for s in spans] == [
        (6, "conversation_create"),
        (7, "context_search"),
        (9, "conversation_add_message"),
    ]
    assert spans[1].parts[0].step == "memory_search"
    assert spans[1].parts[0].n == 2
    assert [str(r.url) for r in seen] == [
        "http://127.0.0.1:7777/api/v1/calls",
        "http://127.0.0.1:7777/api/v1/calls?before=7",
    ]


async def test_reading_is_bounded_and_local_only(make_settings: MakeSettings) -> None:
    local = make_settings(meko_mcp_url="http://127.0.0.1:7777/mcp")
    endless = [[_call(1000 - n, "other")] for n in range(MAX_PAGES + 5)]
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_log(endless, seen)) as http:
        assert await local_trace(http, local, "c1", since=SINCE) == []
    assert len(seen) == MAX_PAGES

    cloud = make_settings(meko_mcp_url="https://mcp.mekodata.ai/mcp")
    with pytest.raises(MekoError, match="local Meko only"):
        calls_url(cloud)

    for body in ({"data": {"calls": "x"}}, {"data": {"calls": [{"id": "x"}]}}):
        transport = httpx.MockTransport(lambda _r, b=body: httpx.Response(200, json=b))
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(MekoProtocolError):
                await local_trace(http, local, "c1", since=SINCE)
    transport = httpx.MockTransport(lambda _r: httpx.Response(401, json={}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(MekoError, match="401"):
            await local_trace(http, local, "c1", since=SINCE)
