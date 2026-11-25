"""The MCP client against a fake Meko (httpx.MockTransport): no network."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from kako.meko.client import (
    MekoAuthError,
    MekoCallLimitError,
    MekoError,
    MekoMcpSession,
    MekoProtocolError,
    MekoToolError,
    MekoUnreachable,
)

URL = "http://meko.test/mcp"
INIT_RESULT = {
    "protocolVersion": "2025-06-18",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "Meko", "version": "1.20261116.0"},
}

Handler = Callable[[httpx.Request], httpx.Response]


class FakeMeko:
    """Records requests and answers initialize as JSON or as an event stream."""

    def __init__(self, *, sse: bool = False, session_id: str | None = "s-1") -> None:
        self.sse = sse
        self.session_id = session_id
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        headers = {"Mcp-Session-Id": self.session_id} if self.session_id else {}
        if request.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202, headers=headers)
        message = {"jsonrpc": "2.0", "id": body["id"], "result": INIT_RESULT}
        if self.sse:
            ping = {"jsonrpc": "2.0", "method": "notifications/message", "params": {}}
            stream = f"event: message\ndata: {json.dumps(ping)}\n\ndata: {json.dumps(message)}\n\n"
            return httpx.Response(
                200, text=stream, headers={**headers, "content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=message, headers=headers)


def client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("sse", [False, True])
async def test_initialize_reads_server_info(sse: bool) -> None:
    fake = FakeMeko(sse=sse)
    async with client(fake) as http, MekoMcpSession(http, URL) as session:
        assert session.server_info is not None
        assert session.server_info.name == "Meko"
        assert session.server_info.version == "1.20261116.0"
    methods = [r.method for r in fake.requests]
    assert methods == ["POST", "POST", "DELETE"]  # initialize, initialized, end session
    initialized = json.loads(fake.requests[1].content)
    assert initialized == {"jsonrpc": "2.0", "method": "notifications/initialized"}


async def test_session_and_protocol_headers_follow_initialize() -> None:
    fake = FakeMeko()
    async with client(fake) as http, MekoMcpSession(http, URL):
        pass
    first, second, _ = fake.requests
    assert "mcp-session-id" not in first.headers
    assert second.headers["mcp-session-id"] == "s-1"
    assert second.headers["mcp-protocol-version"] == "2025-06-18"


async def test_api_key_is_sent_as_bearer_token() -> None:
    fake = FakeMeko()
    async with client(fake) as http, MekoMcpSession(http, URL, SecretStr("mk_test")):
        pass
    assert all(r.headers["authorization"] == "Bearer mk_test" for r in fake.requests)


async def test_every_request_names_the_client() -> None:
    fake = FakeMeko()
    async with client(fake) as http, MekoMcpSession(http, URL):
        pass
    assert all(r.headers["user-agent"].startswith("kako/") for r in fake.requests)


async def test_no_api_key_sends_no_authorization() -> None:
    fake = FakeMeko(session_id=None)
    async with client(fake) as http, MekoMcpSession(http, URL, SecretStr("")):
        pass
    assert all("authorization" not in r.headers for r in fake.requests)
    assert [r.method for r in fake.requests] == ["POST", "POST"]  # no session to end


@pytest.mark.parametrize("status", [401, 403])
async def test_refused_credentials(status: int) -> None:
    async with client(lambda _: httpx.Response(status)) as http:
        with pytest.raises(MekoAuthError, match=f"HTTP {status}"):
            await MekoMcpSession(http, URL).__aenter__()


async def test_server_error() -> None:
    async with client(lambda _: httpx.Response(500)) as http:
        with pytest.raises(MekoError, match="HTTP 500"):
            await MekoMcpSession(http, URL).__aenter__()


async def test_unreachable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with client(refuse) as http:
        with pytest.raises(MekoUnreachable, match="could not be reached"):
            await MekoMcpSession(http, URL).__aenter__()


async def test_jsonrpc_error() -> None:
    def error(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        reply = {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32600, "message": "nope"}}
        return httpx.Response(200, json=reply)

    async with client(error) as http:
        with pytest.raises(MekoError, match="nope"):
            await MekoMcpSession(http, URL).__aenter__()


@pytest.mark.parametrize(
    ("content_type", "text"),
    [
        ("text/html", "<html></html>"),
        ("application/json", "not json"),
        ("application/json", json.dumps({"jsonrpc": "2.0", "id": 99, "result": {}})),
        ("application/json", json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})),
    ],
    ids=["html", "bad-json", "wrong-id", "no-server-info"],
)
async def test_unexpected_answers(content_type: str, text: str) -> None:
    def answer(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=text, headers={"content-type": content_type})

    async with client(answer) as http:
        with pytest.raises(MekoProtocolError):
            await MekoMcpSession(http, URL).__aenter__()


async def test_failed_session_end_does_not_hide_the_result() -> None:
    fake = FakeMeko()

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            raise httpx.ConnectError("gone", request=request)
        return fake(request)

    async with client(flaky) as http, MekoMcpSession(http, URL) as session:
        assert session.server_info is not None


def tool_server(answers: dict[str, dict[str, object]]) -> Handler:
    """A fake Meko whose tools/call answers come from `answers`, keyed by tool name."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            result: dict[str, object] = INIT_RESULT
        else:
            result = answers[body["params"]["name"]]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    return handle


def text_result(text: str, *, is_error: bool = False) -> dict[str, object]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def test_call_tool_parses_json_text() -> None:
    answers = {"memory_search": text_result(json.dumps({"results": [{"id": "m1"}]}))}
    async with (
        client(tool_server(answers)) as http,
        MekoMcpSession(http, URL, max_tool_calls=2) as session,
    ):
        answer = await session.call_tool("memory_search", {"query": "x"})
        assert answer == {"results": [{"id": "m1"}]}
        assert session.tool_calls == {"memory_search": 1}


@pytest.mark.parametrize(
    "result",
    [
        text_result(json.dumps({"error": "conversation_id_required", "detail": "Pass it."})),
        text_result("something broke", is_error=True),
    ],
    ids=["error-key", "is-error"],
)
async def test_call_tool_errors(result: dict[str, object]) -> None:
    async with (
        client(tool_server({"datapack_list": result})) as http,
        MekoMcpSession(http, URL, max_tool_calls=1) as session,
    ):
        with pytest.raises(MekoToolError, match="datapack_list failed"):
            await session.call_tool("datapack_list", {})


async def test_call_tool_without_text_content() -> None:
    async with (
        client(tool_server({"memory_add": {"content": []}})) as http,
        MekoMcpSession(http, URL, max_tool_calls=1) as session,
    ):
        with pytest.raises(MekoProtocolError, match="without text"):
            await session.call_tool("memory_add", {})


async def test_ceiling_stops_calls_before_they_are_sent() -> None:
    fake_calls: list[str] = []
    answers = {"memory_search": text_result("{}")}
    handler = tool_server(answers)

    def counting(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("method") == "tools/call":
            fake_calls.append(body["params"]["name"])
        return handler(request)

    async with client(counting) as http, MekoMcpSession(http, URL, max_tool_calls=2) as session:
        await session.call_tool("memory_search", {})
        await session.call_tool("memory_search", {})
        with pytest.raises(MekoCallLimitError, match="ceiling of 2"):
            await session.call_tool("memory_search", {})
    assert fake_calls == ["memory_search", "memory_search"]


async def test_default_session_makes_no_tool_calls() -> None:
    async with client(tool_server({})) as http, MekoMcpSession(http, URL) as session:
        with pytest.raises(MekoCallLimitError):
            await session.call_tool("memory_search", {})


async def test_call_tool_needs_an_open_session() -> None:
    async with client(tool_server({})) as http:
        with pytest.raises(MekoError, match="before the session"):
            await MekoMcpSession(http, URL, max_tool_calls=1).call_tool("memory_search", {})


def test_negative_ceiling_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        MekoMcpSession(httpx.AsyncClient(), URL, max_tool_calls=-1)
