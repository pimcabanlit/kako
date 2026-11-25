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
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import httpx

from kako.meko.adapter import (
    Band,
    Context,
    DatapackMetrics,
    Document,
    DocumentState,
    Holding,
    KnowledgeHit,
    LoggedSearch,
    Memory,
    Outcome,
    Promoted,
    Replay,
    SelfLearningUnavailable,
    Turn,
    check_agent_id,
    check_document,
)
from kako.meko.client import (
    MekoError,
    MekoMcpSession,
    MekoProtocolError,
    MekoToolError,
    is_not_found,
)
from kako.meko.quota import CallLog, Quota
from kako.settings import LOCAL_HOSTS, Settings

STATES = frozenset({"awaiting_upload", "indexing", "completed", "failed"})
BANDS = frozenset({"high", "mid", "low"})
OUTCOMES = frozenset({"improved", "no_change", "worse", "no_baseline"})


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

    async def search_memories(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 20
    ) -> tuple[Memory, ...]:
        answer = await self._call(
            "memory_search",
            agent_id,
            {
                "conversation_id": conversation_id,
                "query": query,
                "limit": _limit(limit),
                "run_id": conversation_id,
            },
        )
        results = answer.get("results") if isinstance(answer, dict) else None
        if not isinstance(results, list):
            raise MekoProtocolError("memory_search answered without its results")
        return tuple(_memory(m) for m in results)

    async def find_memories(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 10
    ) -> tuple[Memory, ...]:
        answer = await self._call(
            "memory_search",
            agent_id,
            {"conversation_id": conversation_id, "query": query, "limit": _limit(limit)},
        )
        results = answer.get("results") if isinstance(answer, dict) else None
        if not isinstance(results, list):
            raise MekoProtocolError("memory_search answered without its results")
        return tuple(_memory(m) for m in results)

    async def get_memory(
        self, conversation_id: str, memory_id: str, *, agent_id: str
    ) -> Memory | None:
        try:
            answer = await self._call(
                "memory_get_by_id",
                agent_id,
                {"conversation_id": conversation_id, "memory_id": memory_id},
            )
        except MekoToolError as exc:
            if is_not_found(exc):
                return None
            raise
        return _memory(answer)

    async def promote_memories(
        self, conversation_id: str, memory_ids: list[str], *, agent_id: str
    ) -> tuple[str, ...]:
        if not memory_ids:
            return ()
        answer = await self._call(
            "memory_promote",
            agent_id,
            {"conversation_id": conversation_id, "memory_ids": list(memory_ids)},
        )
        if not isinstance(answer, dict):
            raise MekoProtocolError("memory_promote answered without an object")
        done: list[str] = []
        for key in ("inserted_ids", "updated_ids"):
            ids = answer.get(key) or []
            if not isinstance(ids, list):
                raise MekoProtocolError(f"memory_promote's {key} isn't a list")
            done += [str(i) for i in ids]
        return tuple(done)

    async def promoted_memories(self, conversation_id: str, *, agent_id: str) -> Promoted:
        answer = await self._call(
            "memory_get_all", agent_id, {"conversation_id": conversation_id, "promoted": True}
        )
        items = answer.get("promoted_memories") if isinstance(answer, dict) else None
        if not isinstance(items, list):
            raise MekoProtocolError("memory_get_all answered without the promoted memories")
        memories = tuple(_promoted(m) for m in items)
        total = answer.get("total")
        return Promoted(memories, total if isinstance(total, int) else len(memories))

    async def _self_learning(self, tool: str, agent_id: str, arguments: dict[str, Any]) -> Any:
        """A self-learning tool: a deployment that doesn't serve it says it has no such tool. These
        tools take no `agent_id` (Meko Cloud refuses one); the call is counted as the caller's."""
        try:
            return await self._call(tool, agent_id, arguments, agent=False)
        except MekoToolError:
            raise
        except MekoError as exc:
            text = str(exc).lower()
            if "unknown tool" in text or "tool not found" in text:
                raise SelfLearningUnavailable(
                    "this Meko doesn't serve the self-learning tools (Meko Cloud does)"
                ) from None
            raise

    async def logged_searches(
        self, conversation_id: str, *, agent_id: str, band: Literal["low", "mid"]
    ) -> tuple[LoggedSearch, ...]:
        answer = await self._self_learning(
            "selflearning_query_log", agent_id, {"conversation_id": conversation_id, "band": band}
        )
        return tuple(_logged(item) for item in _entries(answer, "selflearning_query_log"))

    async def replay_search(self, conversation_id: str, log_id: str, *, agent_id: str) -> Replay:
        answer = await self._self_learning(
            "selflearning_verify", agent_id, {"conversation_id": conversation_id, "log_id": log_id}
        )
        return _replay(answer)

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

    async def datapack_metrics(
        self, conversation_id: str, *, agent_id: str, days: int = 0
    ) -> DatapackMetrics:
        if not 0 <= days <= 3650:
            raise MekoError("metrics are measured over 0 to 3650 days")
        # The tool takes no `agent_id`; the call is counted as the caller's.
        answer = await self._call(
            "datapack_metrics",
            agent_id,
            {"conversation_id": conversation_id, "days": days},
            agent=False,
        )
        return _metrics(answer)


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
        agent_id=_optional(item.get("agent_id")),
        conversation_id=_optional(item.get("run_id")),
    )


def _promoted(item: Any) -> Memory:
    """A promoted memory as `memory_get_all` lists it: its words are under `data`, and promotion
    dropped its metadata."""
    if not isinstance(item, dict):
        raise MekoProtocolError("a promoted memory in Meko's answer isn't an object")
    return Memory(
        id=_text(item, "id"),
        text=str(item.get("data") or ""),
        metadata={},
        agent_id=_optional(item.get("agent_id")),
        conversation_id=_optional(item.get("conversation_id")),
    )


# Meko's self-learning answers. Meko Cloud (verified Nov 24, docs/meko-setup.md) lists the log under
# `rows`, each with `id`, `query`, `band`, `best_score`, `reason` and `category`, and a replay's
# `before` and `after` as objects with `band` and `best_score`. Other names Meko uses elsewhere are
# still read, leniently; a field Kako needs that isn't there is a protocol error, never a guess.
LIST_KEYS = ("rows", "results", "searches", "items", "entries", "logs", "queries")


def _first(item: dict[str, Any], *keys: str) -> Any:
    return next((item[k] for k in keys if item.get(k) is not None), None)


def _entries(answer: Any, tool: str) -> list[Any]:
    if isinstance(answer, list):
        return answer
    if isinstance(answer, dict):
        for key in LIST_KEYS:
            if isinstance(answer.get(key), list):
                return cast(list[Any], answer[key])
    raise MekoProtocolError(f"{tool} answered without its list of searches")


def _band(value: Any) -> Band | None:
    if value is None:
        return None
    band = str(value).lower()
    if band not in BANDS:
        raise MekoProtocolError(f"a search's band isn't high, mid or low: {band[:20]!r}")
    return cast(Band, band)


def _unit_score(value: Any) -> float | None:
    score = _score(value)
    if score is not None and not 0 <= score <= 1:
        raise MekoProtocolError("a search's score isn't between 0 and 1")
    return score


def _logged(item: Any) -> LoggedSearch:
    if not isinstance(item, dict):
        raise MekoProtocolError("a logged search isn't an object")
    log_id, query = _first(item, "log_id", "id"), _first(item, "query", "prompt")
    band = _band(_first(item, "band", "match_quality", "quality"))
    if not log_id or not isinstance(query, str) or band is None:
        raise MekoProtocolError("a logged search has no log_id, query or band")
    return LoggedSearch(
        log_id=str(log_id),
        query=query,
        band=band,
        score=_unit_score(_first(item, "best_score", "top_score", "score")),
        reason=_optional(item.get("reason")),
        category=_optional(item.get("category")),
    )


def _side(answer: dict[str, Any], side: str) -> tuple[Band | None, float | None]:
    """The band and best score before or after a replay: nested (`before: {band, best_score}`)
    or flat (`band_before`, `best_score_before`)."""
    nested = answer.get(side)
    if isinstance(nested, dict):
        return (
            _band(_first(nested, "band", "match_quality")),
            _unit_score(_first(nested, "best_score", "top_score", "score")),
        )
    return (
        _band(_first(answer, f"band_{side}", f"{side}_band")),
        _unit_score(_first(answer, f"best_score_{side}", f"score_{side}", f"{side}_score")),
    )


def _replay(answer: Any) -> Replay:
    if not isinstance(answer, dict) or answer.get("outcome") not in OUTCOMES:
        raise MekoProtocolError("selflearning_verify answered without an outcome")
    band_before, score_before = _side(answer, "before")
    band_after, score_after = _side(answer, "after")
    return Replay(
        outcome=cast(Outcome, answer["outcome"]),
        band_before=band_before,
        band_after=band_after,
        score_before=score_before,
        score_after=score_after,
        indexing=answer.get("indexing") is True,
        nothing_added=answer.get("nothing_added_since_last_run") is True,
    )


def _optional(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _hit(item: Any) -> KnowledgeHit:
    if not isinstance(item, dict):
        raise MekoProtocolError("a knowledge-base result in Meko's answer isn't an object")
    document_id = item.get("document_id")
    return KnowledgeHit(
        document_id=str(document_id) if document_id else None,
        text=str(item.get("chunk_text") or ""),
        score=_score(item.get("rerank_score", item.get("score"))),
    )


def _whole(value: Any, what: str, *, required: bool = True) -> int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MekoProtocolError(f"datapack_metrics answered without {what} as a count")
    return value


def _part(answer: dict[str, Any], key: str) -> dict[str, Any]:
    part = answer.get(key)
    return part if isinstance(part, dict) else {}


def _holding(size: dict[str, Any], key: str) -> Holding:
    part = _part(size, key)
    return Holding(
        count=_whole(part.get("count", 0), f"{key}' count") or 0,
        tokens=_whole(part.get("tokens", 0), f"{key}' tokens") or 0,
    )


def _metrics(answer: Any) -> DatapackMetrics:
    """`datapack_metrics` as local Meko answers it (Nov 25): `context_size` with `tokens` and
    `knowledge`, `memories` and `conversations` (each `count` and `tokens`), `context_efficiency`
    and `context_relevance`, `days` and `searches`. The size is needed; the rest may be missing on a
    datapack nothing has searched yet."""
    if not isinstance(answer, dict):
        raise MekoProtocolError("datapack_metrics answered without its metrics")
    error = answer.get("error")
    if isinstance(error, str) and error:
        raise MekoToolError(f"datapack_metrics failed: {error[:80]}")
    size = answer.get("context_size")
    if not isinstance(size, dict):
        raise MekoProtocolError("datapack_metrics answered without the context size")
    efficiency = _part(answer, "context_efficiency")
    relevance = _part(answer, "context_relevance")

    def pct(part: dict[str, Any], key: str) -> int | None:
        value = _whole(part.get(key), key, required=False)
        if value is not None and value > 100:
            raise MekoProtocolError(f"datapack_metrics answered with {key} over 100")
        return value

    return DatapackMetrics(
        datapack_id=_optional(answer.get("datapack_id")),
        datapack_name=_optional(answer.get("datapack_name")),
        days=_whole(answer.get("days", 0), "days") or 0,
        searches=_whole(answer.get("searches", 0), "searches") or 0,
        context_tokens=_whole(size.get("tokens"), "the context's tokens") or 0,
        knowledge=_holding(size, "knowledge"),
        memories=_holding(size, "memories"),
        conversations=_holding(size, "conversations"),
        tokens_sent=_whole(efficiency.get("tokens_sent"), "tokens sent", required=False),
        tokens_saved=_whole(efficiency.get("tokens_saved"), "tokens saved", required=False),
        saved_pct=pct(efficiency, "saved_pct"),
        relevance_high=_whole(relevance.get("high"), "high results", required=False),
        relevance_mid=_whole(relevance.get("mid"), "mid results", required=False),
        relevance_low=_whole(relevance.get("low"), "low results", required=False),
        relevant_pct=pct(relevance, "relevant_pct"),
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
