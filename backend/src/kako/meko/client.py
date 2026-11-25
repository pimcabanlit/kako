"""A small MCP client for Meko over Streamable HTTP (JSON-RPC 2.0).

Kako needs a handful of MCP requests, so this is a thin client on httpx rather than an MCP SDK:
one request is one POST; the server answers with JSON or with a short event stream that carries
the response. See https://modelcontextprotocol.io/specification/2025-06-18/basic/transports.
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import SecretStr

from kako import __version__

PROTOCOL_VERSION = "2025-06-18"
_SESSION_HEADER = "Mcp-Session-Id"


class MekoError(Exception):
    """Meko could not be reached or answered with an error."""


class MekoUnreachable(MekoError):
    """Nothing answered at Meko's address: it isn't running there, or the address is wrong."""


class MekoAuthError(MekoError):
    """Meko refused the request's credentials (HTTP 401 or 403)."""


class MekoProtocolError(MekoError):
    """Meko's answer was not the JSON-RPC message expected."""


class MekoToolError(MekoError):
    """A Meko tool ran and reported an error (for example a missing conversation_id)."""


def is_not_found(exc: MekoToolError) -> bool:
    """Whether Meko said the thing asked for doesn't exist (`not_found`, or "No memory found")."""
    text = str(exc).lower()
    return "not found" in text or "not_found" in text


class MekoCallLimitError(MekoError):
    """The session reached its ceiling of tool calls; nothing more is sent to Meko."""


@dataclass(frozen=True)
class ServerInfo:
    name: str
    version: str
    protocol_version: str


class MekoMcpSession:
    """One MCP session: `initialize` on enter, the session closed on exit.

    ```
    async with MekoMcpSession(http, url, api_key, max_tool_calls=10) as session:
        session.server_info.version
        await session.call_tool("memory_search", {...})
    ```

    Every tool call is counted, and a session refuses calls past `max_tool_calls`, so no loop can
    call Meko without a bound. The persistent call counter and quota guard across sessions arrive
    with the adapter in Phase 2 (REVIEW.md rule 9).
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        api_key: SecretStr | None = None,
        *,
        max_tool_calls: int = 0,
        client_name: str = "kako",
    ) -> None:
        if max_tool_calls < 0:
            raise ValueError("max_tool_calls can't be negative")
        self._http = http
        self._url = url
        self._api_key = api_key
        self._client_name = client_name
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._next_id = 1
        self._max_tool_calls = max_tool_calls
        self.server_info: ServerInfo | None = None
        self.tool_calls: Counter[str] = Counter()

    async def __aenter__(self) -> Self:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self._client_name, "version": __version__},
            },
        )
        info = result.get("serverInfo")
        version = result.get("protocolVersion")
        if not isinstance(info, dict) or not isinstance(version, str):
            raise MekoProtocolError("initialize answered without serverInfo or protocolVersion")
        self._protocol_version = version
        self.server_info = ServerInfo(
            name=str(info.get("name", "")),
            version=str(info.get("version", "")),
            protocol_version=version,
        )
        await self._notify("notifications/initialized")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session_id is None:
            return
        # Ending the session is a courtesy: a server may answer 405 (not supported), and a
        # failure here must not hide the result or the error of the work inside the block.
        with contextlib.suppress(httpx.HTTPError):
            await self._http.delete(self._url, headers=self._headers())

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call one Meko tool and return its answer, parsed from JSON.

        Meko answers with one text item holding JSON. A tool that fails answers either with
        `isError` or with an object carrying an `error` key; both raise `MekoToolError`.
        """
        if self.server_info is None:
            raise MekoError("call_tool before the session was opened")
        if sum(self.tool_calls.values()) >= self._max_tool_calls:
            raise MekoCallLimitError(
                f"this session's ceiling of {self._max_tool_calls} Meko tool calls is reached"
            )
        self.tool_calls[name] += 1
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        texts = [
            item.get("text", "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if not texts:
            raise MekoProtocolError(f"{name} answered without text content")
        answer = _parse_json(texts[0]) if texts[0].strip()[:1] in ("{", "[") else texts[0]
        if result.get("isError"):
            raise MekoToolError(f"{name} failed: {_short(answer)}")
        if isinstance(answer, dict) and "error" in answer:
            raise MekoToolError(f"{name} failed: {_short(answer.get('error'))}")
        return answer

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            # Meko Cloud asks every client to name itself; its firewall has refused bare ones.
            "User-Agent": f"{self._client_name}/{__version__}",
        }
        if self._api_key is not None and self._api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self._api_key.get_secret_value()}"
        if self._session_id is not None:
            headers[_SESSION_HEADER] = self._session_id
        if self._protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    async def _post(self, message: dict[str, Any]) -> httpx.Response:
        try:
            response = await self._http.post(self._url, json=message, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise MekoError("Meko did not answer in time") from exc
        except httpx.ConnectError as exc:
            raise MekoUnreachable(f"Meko could not be reached ({type(exc).__name__})") from exc
        except httpx.HTTPError as exc:
            raise MekoError(f"Meko could not be reached ({type(exc).__name__})") from exc
        if response.status_code in (401, 403):
            raise MekoAuthError(f"Meko refused the credentials (HTTP {response.status_code})")
        if response.status_code >= 400:
            raise MekoError(f"Meko answered HTTP {response.status_code}")
        session_id = response.headers.get(_SESSION_HEADER)
        if session_id:
            self._session_id = session_id
        return response

    async def _notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method})

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        response = await self._post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        message = _find_response(response, request_id)
        if "error" in message:
            error = message["error"]
            text = error.get("message", "unknown error") if isinstance(error, dict) else error
            raise MekoError(f"Meko answered {method} with an error: {text}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise MekoProtocolError(f"{method} answered without a result object")
        return result


def _find_response(response: httpx.Response, request_id: int) -> dict[str, Any]:
    """The JSON-RPC response to `request_id`, from a JSON body or an event stream."""
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "application/json":
        messages = [_parse_json(response.text)]
    elif content_type == "text/event-stream":
        messages = [_parse_json(data) for data in _sse_data(response.text)]
    else:
        raise MekoProtocolError(f"unexpected content type {content_type or 'none'}")
    for message in messages:
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    raise MekoProtocolError(f"no response to request {request_id} in Meko's answer")


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise MekoProtocolError("Meko's answer was not valid JSON") from exc


def _short(value: Any) -> str:
    return str(value)[:200]


def _sse_data(body: str) -> list[str]:
    """The data of each event in a server-sent event stream (multi-line data joined)."""
    events: list[str] = []
    lines: list[str] = []
    for raw in body.splitlines():
        if raw == "":
            if lines:
                events.append("\n".join(lines))
                lines = []
        elif raw.startswith("data:"):
            lines.append(raw[5:].removeprefix(" "))
    if lines:
        events.append("\n".join(lines))
    return events
