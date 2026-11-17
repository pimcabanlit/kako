"""A small MCP client for Meko over Streamable HTTP (JSON-RPC 2.0).

Kako needs a handful of MCP requests, so this is a thin client on httpx rather than an MCP SDK:
one request is one POST; the server answers with JSON or with a short event stream that carries
the response. See https://modelcontextprotocol.io/specification/2025-06-18/basic/transports.
"""

from __future__ import annotations

import contextlib
import json
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


class MekoAuthError(MekoError):
    """Meko refused the request's credentials (HTTP 401 or 403)."""


class MekoProtocolError(MekoError):
    """Meko's answer was not the JSON-RPC message expected."""


@dataclass(frozen=True)
class ServerInfo:
    name: str
    version: str
    protocol_version: str


class MekoMcpSession:
    """One MCP session: `initialize` on enter, the session closed on exit.

    ```
    async with MekoMcpSession(http, url, api_key) as session:
        session.server_info.version
    ```
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        api_key: SecretStr | None = None,
        *,
        client_name: str = "kako",
    ) -> None:
        self._http = http
        self._url = url
        self._api_key = api_key
        self._client_name = client_name
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._next_id = 1
        self.server_info: ServerInfo | None = None

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

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
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
