"""A session's trace: every Meko call made with its conversation, as spans.

On Meko Cloud the trace is the conversation's page in the Observe hub (`Settings.meko_trace_url`),
which shows each tool call as a span. Local Meko keeps the same calls in its call log, one row per
MCP tool call with the conversation id, its latency and its parts (`steps`), and serves it to the
web UI's Calls page at `/api/v1/calls`. `local_trace` reads that log for one conversation.

It reads local Meko only, and refuses any other host. It is a read of Meko's own log, not an MCP
tool call: no allowance is spent, so it isn't counted in `meko_call`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

import httpx

from kako.meko.client import MekoError, MekoProtocolError
from kako.settings import Settings

MAX_PAGES: Final = 20  # the call log is read newest first, a page at a time; never unbounded


@dataclass(frozen=True)
class Part:
    step: str  # such as memory_search, knowledge_base_search
    ms: int
    n: int | None  # results, for a search


@dataclass(frozen=True)
class Span:
    """One Meko tool call made with the conversation."""

    call_id: int
    at: datetime
    tool: str
    agent_id: str
    ms: int
    ok: bool
    error_code: str
    parts: tuple[Part, ...]


def calls_url(settings: Settings) -> str:
    """Local Meko's call log, next to its MCP endpoint."""
    if settings.meko_target != "local":
        raise MekoError("the call log is read from local Meko only; Meko Cloud has its trace page")
    parts = urlsplit(settings.meko_mcp_url)
    return urlunsplit((parts.scheme, parts.netloc, "/api/v1/calls", "", ""))


async def local_trace(
    http: httpx.AsyncClient, settings: Settings, conversation_id: str, *, since: datetime
) -> list[Span]:
    """The conversation's calls in local Meko's log, oldest first. Pages are read back to `since`
    (the session's start), at most `MAX_PAGES` of them."""
    url = calls_url(settings)
    headers = {}
    if settings.meko_api_key is not None:
        headers["Authorization"] = f"Bearer {settings.meko_api_key.get_secret_value()}"
    found: list[Span] = []
    before: int | None = None
    for _ in range(MAX_PAGES):
        params = {} if before is None else {"before": str(before)}
        response = await http.get(url, params=params, headers=headers)
        if response.status_code != 200:
            raise MekoError(f"local Meko's call log answered {response.status_code}")
        page = _page(response.json())
        calls, more = page
        for call in calls:
            span = _span(call)
            if span.at < since:
                return sorted(found, key=lambda s: s.call_id)
            if call.get("conversation_id") == conversation_id:
                found.append(span)
        if not more or not calls:
            break
        before = _span(calls[-1]).call_id
    return sorted(found, key=lambda s: s.call_id)


def _page(body: Any) -> tuple[list[dict[str, Any]], bool]:
    data = body.get("data") if isinstance(body, dict) else None
    calls = data.get("calls") if isinstance(data, dict) else None
    if not isinstance(calls, list) or not all(isinstance(c, dict) for c in calls):
        raise MekoProtocolError("local Meko's call log isn't a list of calls")
    return calls, bool(data.get("more")) if isinstance(data, dict) else False


def _span(call: dict[str, Any]) -> Span:
    try:
        parts = tuple(
            Part(
                str(p["step"]),
                int(p.get("ms", 0)),
                p.get("n") if isinstance(p.get("n"), int) else None,
            )
            for p in call.get("steps") or []
        )
        return Span(
            call_id=int(call["id"]),
            at=datetime.fromisoformat(str(call["at"])),
            tool=str(call["tool"]),
            agent_id=str(call.get("agent_id", "")),
            ms=int(call.get("ms", 0)),
            ok=bool(call.get("ok")),
            error_code=str(call.get("error_code", "")),
            parts=parts,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MekoProtocolError(f"a call in local Meko's log is malformed: {exc}") from None
