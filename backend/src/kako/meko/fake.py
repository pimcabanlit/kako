"""`FakeMeko`: the Meko adapter in memory, for unit tests. No network.

It keeps conversations, memories and documents, and searches by shared words (a score from 0 to 1),
which is enough to test what Kako does with Meko's answers, not Meko's ranking. Every call goes
through the same quota guard as `McpMeko`, so the call counter is tested on it too.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from kako.meko.adapter import (
    Context,
    Document,
    KnowledgeHit,
    Memory,
    Turn,
    check_agent_id,
    check_document,
)
from kako.meko.client import MekoError, MekoToolError
from kako.meko.quota import CallResult, MemoryCallLog, Quota


@dataclass
class _Conversation:
    title: str
    agent_id: str
    turns: list[Turn] = field(default_factory=list)


@dataclass
class _Memory:
    text: str
    metadata: dict[str, Any]
    agent_id: str


@dataclass
class _Document:
    filename: str
    text: str
    document_id: str


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score(query: str, text: str) -> float:
    asked = _words(query)
    return len(asked & _words(text)) / len(asked) if asked else 0.0


class FakeMeko:
    """The `Meko` interface in memory. `calls` lists each tool called, in order."""

    def __init__(self, quota: Quota | None = None, datapack_id: str | None = None) -> None:
        self.quota = quota or Quota(MemoryCallLog(), "local", 0)
        self.datapack_id = datapack_id
        self.conversations: dict[str, _Conversation] = {}
        self.sessions: dict[str, str] = {}
        self.memories: dict[str, _Memory] = {}
        self.documents: dict[str, _Document] = {}  # by upload key
        self.calls: list[str] = []

    @asynccontextmanager
    async def _call(
        self, tool: str, agent_id: str, conversation_id: str | None
    ) -> AsyncIterator[CallResult]:
        """Like McpMeko: the agent id is checked, then the call is counted, then made."""
        check_agent_id(agent_id)
        async with self.quota.call(tool, agent_id) as result:
            self.calls.append(tool)
            if conversation_id is not None and conversation_id not in self.conversations:
                raise MekoToolError(f"{tool} failed: conversation {conversation_id} not found")
            yield result

    async def create_conversation(
        self, *, agent_id: str, title: str, session_key: str | None = None
    ) -> str:
        async with self._call("conversation_create", agent_id, None):
            if session_key is not None and session_key in self.sessions:
                return self.sessions[session_key]
            conversation_id = uuid.uuid4().hex
            self.conversations[conversation_id] = _Conversation(title, agent_id)
            if session_key is not None:
                self.sessions[session_key] = conversation_id
            return conversation_id

    async def add_turn(self, conversation_id: str, turn: Turn, *, agent_id: str) -> str:
        async with self._call("conversation_add_message", agent_id, conversation_id):
            turns = self.conversations[conversation_id].turns
            if turn.seed is None or all(t.seed != turn.seed for t in turns):
                turns.append(turn)
            return hashlib.sha256(
                f"{conversation_id}:{turn.seed or len(turns)}".encode()
            ).hexdigest()

    async def delete_conversation(self, conversation_id: str, *, agent_id: str) -> None:
        async with self._call("conversation_delete", agent_id, conversation_id):
            if self.conversations[conversation_id].agent_id != agent_id:
                raise MekoToolError("conversation_delete failed: only its creator can delete it")
            del self.conversations[conversation_id]

    async def add_memory(
        self, conversation_id: str, text: str, metadata: dict[str, Any], *, agent_id: str
    ) -> str:
        async with self._call("memory_add", agent_id, conversation_id):
            memory_id = str(uuid.uuid4())
            self.memories[memory_id] = _Memory(text, dict(metadata), agent_id)
            return memory_id

    def _own(self, tool: str, memory_id: str, agent_id: str) -> _Memory:
        memory = self.memories.get(memory_id)
        if memory is None:
            raise MekoToolError(f"{tool} failed: memory {memory_id} not found")
        if memory.agent_id != agent_id:
            raise MekoToolError(f"{tool} failed: only the agent that wrote it can change it")
        return memory

    async def update_memory(
        self, conversation_id: str, memory_id: str, text: str, *, agent_id: str
    ) -> None:
        async with self._call("memory_update", agent_id, conversation_id):
            self._own("memory_update", memory_id, agent_id).text = text

    async def delete_memory(self, conversation_id: str, memory_id: str, *, agent_id: str) -> None:
        async with self._call("memory_delete_by_id", agent_id, conversation_id):
            self._own("memory_delete_by_id", memory_id, agent_id)
            del self.memories[memory_id]

    def _knowledge(self, query: str, limit: int) -> tuple[KnowledgeHit, ...]:
        hits = [
            KnowledgeHit(d.document_id, d.text, _score(query, d.text))
            for d in self.documents.values()
        ]
        hits = [h for h in hits if h.score]
        return tuple(sorted(hits, key=lambda h: -(h.score or 0))[:limit])

    async def search_context(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 5
    ) -> Context:
        _check_limit(limit)
        async with self._call("context_search", agent_id, conversation_id) as result:
            memories = [
                Memory(i, m.text, dict(m.metadata), _score(query, m.text))
                for i, m in self.memories.items()
            ]
            found = tuple(sorted((m for m in memories if m.score), key=lambda m: -(m.score or 0)))
            context = Context(found[:limit], self._knowledge(query, limit))
            result.result_count = len(context.memories) + len(context.knowledge)
            return context

    async def search_knowledge(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 5
    ) -> tuple[KnowledgeHit, ...]:
        _check_limit(limit)
        async with self._call("knowledgebase_search", agent_id, conversation_id) as result:
            hits = self._knowledge(query, limit)
            result.result_count = len(hits)
            return hits

    async def upload_document(
        self, conversation_id: str, filename: str, content: bytes, *, agent_id: str
    ) -> Document:
        check_document(filename, content)
        async with self._call("knowledgebase_upload_document", agent_id, conversation_id):
            key = f"{hashlib.sha256(content).hexdigest()}/{filename}"
            if key in self.documents:
                return Document(key, filename, "completed", already_uploaded=True)
            self.documents[key] = _Document(
                filename, content.decode("utf-8", "replace"), str(uuid.uuid4())
            )
            return Document(key, filename, "indexing")

    async def document_status(self, conversation_id: str, key: str, *, agent_id: str) -> Document:
        async with self._call("knowledgebase_document_status", agent_id, conversation_id):
            document = self.documents.get(key)
            if document is None:
                raise MekoToolError(f"knowledgebase_document_status failed: no document {key}")
            # Like Meko: the status names no document id; search hits carry it.
            return Document(key, document.filename, "completed")

    async def delete_document(
        self, conversation_id: str, document_id: str, *, agent_id: str
    ) -> None:
        async with self._call("knowledgebase_delete_document", agent_id, conversation_id):
            key = next((k for k, d in self.documents.items() if d.document_id == document_id), None)
            if key is None:
                raise MekoToolError(f"knowledgebase_delete_document failed: no {document_id}")
            del self.documents[key]


def _check_limit(limit: int) -> None:
    if not 1 <= limit <= 50:
        raise MekoError("a search asks for 1 to 50 results")
