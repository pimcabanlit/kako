"""The Meko adapter: one interface for every Meko call Kako makes (docs/data-model.md, "What Kako
keeps in Meko"), with two implementations: `McpMeko` (Meko over MCP) and `FakeMeko` (memory, for
unit tests).

Every call names its `agent_id` (`kako:<role>`) and the conversation it belongs to, and goes through
the quota guard (`quota.py`) before anything is sent. Memories are where agents find context, never
the source of a number: figures come from the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

from kako.meko.client import MekoError

AGENT_ID: Final = re.compile(r"kako:[a-z][a-z_-]*")
DocumentState = Literal["awaiting_upload", "indexing", "completed", "failed"]
Band = Literal["high", "mid", "low"]  # a search's match quality: best score 0.75+, 0.50+, below
Outcome = Literal["improved", "no_change", "worse", "no_baseline"]
# File types Meko's knowledge base takes (knowledgebase_upload_document), up to 50 MiB.
DOCUMENT_TYPES: Final = frozenset(
    {".pdf", ".txt", ".text", ".md", ".csv", ".json", ".xml", ".html", ".htm"}
)
MAX_DOCUMENT_BYTES: Final = 50 * 1024 * 1024


def check_agent_id(agent_id: str) -> str:
    """`kako:<role>`, such as `kako:orchestrator`: every write and trace names the agent."""
    if not AGENT_ID.fullmatch(agent_id):
        raise MekoError(f"agent_id must be kako:<role>, not {agent_id!r}")
    return agent_id


@dataclass(frozen=True)
class Turn:
    """One turn of a planning session, with how Kako got to its answer (docs/meko-setup.md)."""

    input: str
    output: str
    plan: tuple[str, ...] = ()
    reasoning: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    seed: str | None = None  # the same seed is the same turn: a retry stores it once


@dataclass(frozen=True)
class Memory:
    id: str
    text: str
    metadata: dict[str, Any]
    score: float | None = None  # a search's relevance, 0 to 1
    agent_id: str | None = None  # who wrote it: only that agent can change or delete it
    conversation_id: str | None = None  # the conversation it was saved in (Meko's `run_id`)


@dataclass(frozen=True)
class Promoted:
    """`memory_get_all` with `promoted`: the datapack's newest promoted memories (Meko lists at
    most 20) and how many it holds in all."""

    memories: tuple[Memory, ...]
    total: int

    @property
    def complete(self) -> bool:
        """Every promoted memory is listed, so one not listed isn't in collective memory."""
        return len(self.memories) >= self.total


@dataclass(frozen=True)
class KnowledgeHit:
    document_id: str | None
    text: str
    score: float | None = None


@dataclass(frozen=True)
class Context:
    """`context_search`: memories and knowledge-base excerpts, each source in its own list."""

    memories: tuple[Memory, ...]
    knowledge: tuple[KnowledgeHit, ...]


@dataclass(frozen=True)
class Document:
    """A knowledge-base file, known by its upload key. Meko's status doesn't name the document id
    (search hits do), so `document_id` is set only when Meko gives it."""

    key: str
    filename: str
    state: DocumentState
    document_id: str | None = None
    already_uploaded: bool = False
    message: str | None = None


class SelfLearningUnavailable(MekoError):
    """This Meko doesn't serve the self-learning tools (local Meko doesn't; Meko Cloud does)."""


@dataclass(frozen=True)
class LoggedSearch:
    """One `context_search` in Meko's search log (`selflearning_query_log`)."""

    log_id: str
    query: str
    band: Band
    score: float | None  # the best result's score, 0 to 1; None: nothing came back
    reason: str | None = None  # why it fell short, such as `weak_match`
    category: str | None = None  # such as `coverage`


@dataclass(frozen=True)
class Replay:
    """`selflearning_verify`: one logged search run again, and how it matched before and after."""

    outcome: Outcome
    band_before: Band | None
    band_after: Band | None
    score_before: float | None
    score_after: float | None
    indexing: bool  # content added is still being indexed: replay again once it is done
    nothing_added: bool  # nothing changed since the last replay: this one isn't new


@dataclass(frozen=True)
class Holding:
    """One part of a datapack: how many items, and their tokens as Meko estimates them."""

    count: int
    tokens: int


@dataclass(frozen=True)
class DatapackMetrics:
    """`datapack_metrics`: a datapack's context as Meko measures it (its web UI's Overview)."""

    datapack_id: str | None
    datapack_name: str | None
    days: int  # the searches of the last this many days are measured
    searches: int
    context_tokens: int  # everything the datapack holds
    knowledge: Holding
    memories: Holding
    conversations: Holding
    # Context efficiency: the tokens context_search sent, against sending the whole knowledge base.
    tokens_sent: int | None
    tokens_saved: int | None
    saved_pct: int | None
    # Context relevance: search results by band, and the share scoring 0.5 or more.
    relevance_high: int | None
    relevance_mid: int | None
    relevance_low: int | None
    relevant_pct: int | None


def check_document(filename: str, content: bytes) -> None:
    suffix = filename[filename.rfind(".") :].lower() if "." in filename else ""
    if suffix not in DOCUMENT_TYPES:
        raise MekoError(f"{filename}: Meko's knowledge base doesn't take {suffix or 'this'} files")
    if not content:
        raise MekoError(f"{filename} is empty")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise MekoError(f"{filename} is over Meko's 50 MiB limit")


class Meko(Protocol):
    """Every Meko call Kako makes. Each one raises a `MekoError` subclass when it can't be done,
    and `MekoQuotaError` when the call counter refuses it."""

    @property
    def datapack_id(self) -> str | None:
        """The datapack every call goes to; None: the account's default one."""
        ...

    async def create_conversation(
        self, *, agent_id: str, title: str, session_key: str | None = None
    ) -> str:
        """A conversation for a planning session; the same `session_key` reconnects the same one."""
        ...

    async def add_turn(self, conversation_id: str, turn: Turn, *, agent_id: str) -> str:
        """Store one turn; returns its message id."""
        ...

    async def read_turns(self, conversation_id: str, *, agent_id: str) -> list[Turn]:
        """The conversation's turns, oldest first, as kept: the trace's plan, reasoning and ids
        (a turn read back carries no seed)."""
        ...

    async def delete_conversation(self, conversation_id: str, *, agent_id: str) -> None: ...

    async def add_memory(
        self, conversation_id: str, text: str, metadata: dict[str, Any], *, agent_id: str
    ) -> str:
        """Save one sentence word for word; returns the memory's id."""
        ...

    async def update_memory(
        self, conversation_id: str, memory_id: str, text: str, *, agent_id: str
    ) -> None:
        """Rewrite a memory (a replaced fact, in the past tense). Its metadata stays."""
        ...

    async def delete_memory(self, conversation_id: str, memory_id: str, *, agent_id: str) -> None:
        """Delete a memory for good (a retracted fact, a rejected candidate)."""
        ...

    async def search_memories(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 20
    ) -> tuple[Memory, ...]:
        """The memories saved in this conversation that match `query`, Kako's own and those Meko
        extracted on its own (`memory_search` with the conversation as `run_id`; Meko leaves out
        weak matches). Each names the agent that wrote it."""
        ...

    async def find_memories(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 10
    ) -> tuple[Memory, ...]:
        """The datapack's memories that match `query`, from every conversation and agent
        (`memory_search`; Meko leaves out weak matches)."""
        ...

    async def get_memory(
        self, conversation_id: str, memory_id: str, *, agent_id: str
    ) -> Memory | None:
        """One memory by its id, None when Meko holds no such memory (a promoted one is no longer
        a memory: see `promoted_memories`)."""
        ...

    async def promote_memories(
        self, conversation_id: str, memory_ids: list[str], *, agent_id: str
    ) -> tuple[str, ...]:
        """Move memories into the datapack's collective memory, which every agent relies on; returns
        the ids promoted now. It can't be undone: a promoted memory can't be changed or deleted, and
        memory search no longer finds it (`promoted_memories` lists it)."""
        ...

    async def promoted_memories(self, conversation_id: str, *, agent_id: str) -> Promoted:
        """The datapack's newest promoted memories, each with the agent that wrote it."""
        ...

    async def logged_searches(
        self, conversation_id: str, *, agent_id: str, band: Literal["low", "mid"]
    ) -> tuple[LoggedSearch, ...]:
        """The newest `context_search` calls on the datapack that matched in `band` (Meko's search
        log, its first page of 10, from the last 7 days). Raises `SelfLearningUnavailable` where
        Meko doesn't serve self-learning."""
        ...

    async def replay_search(self, conversation_id: str, log_id: str, *, agent_id: str) -> Replay:
        """Run a logged search again and say how it matched before and after. It counts as a
        `context_search`. Raises `SelfLearningUnavailable` where Meko doesn't serve it."""
        ...

    async def search_context(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 5
    ) -> Context:
        """Memories and the knowledge base at once. The brief's search, and the only one Meko's
        self-learning log counts."""
        ...

    async def search_knowledge(
        self, conversation_id: str, query: str, *, agent_id: str, limit: int = 5
    ) -> tuple[KnowledgeHit, ...]: ...

    async def upload_document(
        self, conversation_id: str, filename: str, content: bytes, *, agent_id: str
    ) -> Document:
        """Upload a file to the knowledge base. The same content is uploaded once
        (`already_uploaded`). Indexing goes on after this returns: see `document_status`."""
        ...

    async def document_status(
        self, conversation_id: str, key: str, *, agent_id: str
    ) -> Document: ...

    async def delete_document(
        self, conversation_id: str, document_id: str, *, agent_id: str
    ) -> None: ...

    async def datapack_metrics(
        self, conversation_id: str, *, agent_id: str, days: int = 0
    ) -> DatapackMetrics:
        """The datapack's context size, efficiency and relevance, over the searches of the last
        `days` days (0: all Meko's call log keeps). Read only; not a capped tool."""
        ...
