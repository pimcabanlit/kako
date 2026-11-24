"""`McpMeko`: the Meko adapter over MCP, on `MekoMcpSession`.

```
async with open_meko(settings, call_log) as meko:
    conversation_id = await meko.create_conversation(agent_id="kako:orchestrator", title="...")
```

Every call goes through the quota guard first, and the session refuses calls past
`KAKO_MEKO_SESSION_MAX_CALLS`, so nothing here can call Meko without a bound.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from kako.meko.adapter import (
    Context,
    Document,
    DocumentState,
    KnowledgeHit,
    Memory,
    Turn,
    check_agent_id,
    check_document,
)
from kako.meko.client import MekoError, MekoMcpSession, MekoProtocolError
from kako.meko.quota import CallLog, Quota
from kako.settings import LOCAL_HOSTS, Settings

STATES = frozenset({"awaiting_upload", "indexing", "completed", "failed"})


class McpMeko:
    """The `Meko` interface on one MCP session."""

    def __init__(
        self,
        session: MekoMcpSession,
        quota: Quota,
        uploads: httpx.AsyncClient,
        datapack_id: str | None = None,
    ) -> None:
        """`uploads` posts files to Meko's one-time links: keep it apart from the MCP session's."""
        self._session = session
        self._quota = quota
        self._uploads = uploads
        self._datapack_id = datapack_id

    @property
    def datapack_id(self) -> str | None:
        return self._datapack_id

    async def _call(
        self, tool: str, agent_id: str, arguments: dict[str, Any], *, agent: bool = True
    ) -> Any:
        check_agent_id(agent_id)
        args = dict(arguments)
        if agent:
            args["agent_id"] = agent_id
        if self._datapack_id is not None:
            args["datapack_id"] = self._datapack_id
        async with self._quota.call(tool, agent_id) as result:
            answer = await self._session.call_tool(tool, args)
            if tool.endswith("_search"):
                result.result_count = _count(answer)
        return answer

    async def create_conversation(
        self, *, agent_id: str, title: str, session_key: str | None = None
    ) -> str:
        args: dict[str, Any] = {"title": title}
        if session_key is not None:
            args["session_id"] = session_key
        return _text(await self._call("conversation_create", agent_id, args), "id")

    async def add_turn(self, conversation_id: str, turn: Turn, *, agent_id: str) -> str:
        args: dict[str, Any] = {
            "conversation_id": conversation_id,
            "input": turn.input,
            "output": turn.output,
        }
        if turn.plan:
            args["plan"] = list(turn.plan)
        if turn.reasoning is not None:
            args["reasoning"] = turn.reasoning
        if turn.metadata:
            args["metadata"] = json.dumps(turn.metadata)
        if turn.seed is not None:
            args["seed"] = turn.seed
        return _text(await self._call("conversation_add_message", agent_id, args), "message_id")

    async def read_turns(self, conversation_id: str, *, agent_id: str) -> list[Turn]:
        answer = await self._call(
            "conversation_get",
            agent_id,
            {"conversation_id": conversation_id, "include_messages": True},
        )
        messages = answer.get("messages") if isinstance(answer, dict) else None
        if not isinstance(messages, list):
            raise MekoProtocolError("conversation_get didn't answer with the messages")
        return [_turn(m) for m in messages]

    async def delete_conversation(self, conversation_id: str, *, agent_id: str) -> None:
        await self._call("conversation_delete", agent_id, {"conversation_id": conversation_id})

    async def add_memory(
        self, conversation_id: str, text: str, metadata: dict[str, Any], *, agent_id: str
    ) -> str:
        answer = await self._call(
            "memory_add",
            agent_id,
            {"conversation_id": conversation_id, "text": text, "metadata": json.dumps(metadata)},
        )
        results = answer.get("results") if isinstance(answer, dict) else None
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise MekoProtocolError("memory_add didn't answer with the one memory it saved")
        return _text(results[0], "id")

    async def update_memory(
        self, conversation_id: str, memory_id: str, text: str, *, agent_id: str
    ) -> None:
        await self._call(
            "memory_update",
            agent_id,
            {"conversation_id": conversation_id, "memory_id": memory_id, "text": text},
        )

    async def delete_memory(self, conversation_id: str, memory_id: str, *, agent_id: str) -> None:
        await self._call(
            "memory_delete_by_id",
            agent_id,
            {"conversation_id": conversation_id, "memory_id": memory_id},
        )

    async def search_context(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 5
    ) -> Context:
        answer = await self._call(
            "context_search",
            agent_id,
            {"conversation_id": conversation_id, "query": query, "limit": _limit(limit)},
        )
        results = answer.get("results") if isinstance(answer, dict) else None
        if not isinstance(results, dict):
            raise MekoProtocolError("context_search answered without its results")
        return Context(
            tuple(_memory(m) for m in results.get("memory") or ()),
            tuple(_hit(h) for h in results.get("knowledge_base") or ()),
        )

    async def search_knowledge(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 5
    ) -> tuple[KnowledgeHit, ...]:
        answer = await self._call(
            "knowledgebase_search",
            agent_id,
            {
                "conversation_id": conversation_id,
                "query": query,
                "limit": _limit(limit),
                # Required by the tool; blank means the default datapack. `_call` sets it when a
                # datapack is configured.
                "datapack_id": "",
            },
        )
        results = answer.get("results") if isinstance(answer, dict) else None
        if not isinstance(results, list):
            raise MekoProtocolError("knowledgebase_search answered without its results")
        return tuple(_hit(h) for h in results)

    async def upload_document(
        self, conversation_id: str, filename: str, content: bytes, *, agent_id: str
    ) -> Document:
        check_document(filename, content)
        answer = await self._call(
            "knowledgebase_upload_document",
            agent_id,
            {
                "conversation_id": conversation_id,
                "filename": filename,
                "size": len(content),
                "content_hash": hashlib.sha256(content).hexdigest(),
                "content_head_base64": base64.b64encode(content[:3072]).decode("ascii"),
            },
        )
        if not isinstance(answer, dict):
            raise MekoProtocolError("knowledgebase_upload_document answered without an object")
        key = _text(answer, "key")
        if answer.get("already_uploaded") is True:
            return Document(key, filename, "indexing", already_uploaded=True)
        url, fields = answer.get("url"), answer.get("fields") or {}
        if not isinstance(url, str) or not isinstance(fields, dict):
            raise MekoProtocolError("knowledgebase_upload_document answered without its link")
        await self._post_file(url, {str(k): str(v) for k, v in fields.items()}, filename, content)
        return Document(key, filename, "indexing")

    async def _post_file(
        self, url: str, fields: dict[str, str], filename: str, content: bytes
    ) -> None:
        """POST the file to the one-time link Meko gave. The link carries its own authorisation,
        so the API key is never sent with it; plain http only to this machine."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise MekoProtocolError("Meko's upload link isn't an http(s) URL")
        if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
            raise MekoError("Meko's upload link must use https:// unless it is on this machine")
        try:
            response = await self._uploads.post(
                url, data=fields, files={"file": (filename, content)}, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            raise MekoError(f"the upload of {filename} failed ({type(exc).__name__})") from exc
        if response.status_code >= 300:
            raise MekoError(f"the upload of {filename} was refused (HTTP {response.status_code})")

    async def document_status(self, conversation_id: str, key: str, *, agent_id: str) -> Document:
        answer = await self._call(
            "knowledgebase_document_status",
            agent_id,
            {"conversation_id": conversation_id, "document_key": key},
        )
        if not isinstance(answer, dict) or answer.get("state") not in STATES:
            raise MekoProtocolError("knowledgebase_document_status answered without a state")
        document_id = answer.get("document_id")
        return Document(
            key=key,
            filename=str(answer.get("filename") or key.rsplit("/", 1)[-1]),
            state=cast(DocumentState, answer["state"]),
            document_id=str(document_id) if document_id else None,
            message=str(answer["message"]) if answer.get("message") else None,
        )

    async def delete_document(
        self, conversation_id: str, document_id: str, *, agent_id: str
    ) -> None:
        # This tool takes no agent_id; the call is still counted under the caller's.
        await self._call(
            "knowledgebase_delete_document",
            agent_id,
            {"conversation_id": conversation_id, "document_id": document_id},
            agent=False,
        )


@asynccontextmanager
async def open_meko(
    settings: Settings, log: CallLog, *, max_calls: int | None = None
) -> AsyncIterator[McpMeko]:
    """One adapter session on the configured Meko, counted in `log`. It sends at most `max_calls`
    tool calls (default: KAKO_MEKO_SESSION_MAX_CALLS)."""
    quota = Quota(log, settings.meko_target, settings.meko_cloud_ceiling)
    # Uploads get a client of their own, so nothing the MCP server set (a cookie, say) can travel
    # with a file to the upload link's host.
    async with (
        httpx.AsyncClient(timeout=60) as http,
        httpx.AsyncClient(timeout=60) as uploads,
        MekoMcpSession(
            http,
            settings.meko_mcp_url,
            settings.meko_api_key,
            max_tool_calls=max_calls or settings.meko_session_max_calls,
        ) as session,
    ):
        yield McpMeko(session, quota, uploads, settings.meko_datapack_id)


def _limit(limit: int) -> int:
    if not 1 <= limit <= 50:
        raise MekoError("a search asks for 1 to 50 results")
    return limit


def _turn(item: Any) -> Turn:
    if not isinstance(item, dict):
        raise MekoProtocolError("a conversation message isn't an object")
    metadata = item.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            raise MekoProtocolError("a message's metadata isn't JSON") from None
    plan = item.get("plan") or []
    if not isinstance(metadata, dict) or not isinstance(plan, list):
        raise MekoProtocolError("a message's plan or metadata has the wrong shape")
    reasoning = item.get("reasoning")
    return Turn(
        input=str(item.get("input") or ""),
        output=str(item.get("output") or ""),
        plan=tuple(str(step) for step in plan),
        reasoning=reasoning if isinstance(reasoning, str) and reasoning else None,
        metadata=metadata,
    )


def _text(answer: Any, key: str) -> str:
    value = answer.get(key) if isinstance(answer, dict) else None
    if not isinstance(value, str) or not value:
        raise MekoProtocolError(f"Meko's answer has no {key}")
    return value


def _score(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _memory(item: Any) -> Memory:
    if not isinstance(item, dict):
        raise MekoProtocolError("a memory in Meko's answer isn't an object")
    metadata = item.get("metadata")
    return Memory(
        id=_text(item, "id"),
        text=str(item.get("memory") or ""),
        metadata=metadata if isinstance(metadata, dict) else {},
        score=_score(item.get("score")),
    )


def _hit(item: Any) -> KnowledgeHit:
    if not isinstance(item, dict):
        raise MekoProtocolError("a knowledge-base result in Meko's answer isn't an object")
    document_id = item.get("document_id")
    return KnowledgeHit(
        document_id=str(document_id) if document_id else None,
        text=str(item.get("chunk_text") or ""),
        score=_score(item.get("rerank_score", item.get("score"))),
    )


def _count(answer: Any) -> int | None:
    """How many results a search returned, for the call log."""
    if not isinstance(answer, dict):
        return None
    results = answer.get("results")
    if isinstance(results, list):
        return len(results)
    if isinstance(results, dict):
        return sum(len(v) for v in results.values() if isinstance(v, list))
    return None
