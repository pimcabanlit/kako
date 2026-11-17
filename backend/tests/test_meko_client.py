"""The MCP client against a fake Meko (httpx.MockTransport): no network."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from kako.meko.client import (
    MekoAuthError,
    MekoError,
    MekoMcpSession,
    MekoProtocolError,
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
        with pytest.raises(MekoError, match="could not be reached"):
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
