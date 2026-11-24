"""The Meko adapter: `McpMeko` against a scripted MCP server (no network), `FakeMeko`, and the
demo documents' upload."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kako.demo.files import read_demo
from kako.demo.kb import DemoUploadError, upload_demo_documents
from kako.meko.adapter import Document, Turn, check_agent_id
from kako.meko.client import MekoError, MekoMcpSession, MekoProtocolError, MekoToolError
from kako.meko.fake import FakeMeko
from kako.meko.mcp import McpMeko
from kako.meko.quota import MekoQuotaError, MemoryCallLog, Quota
from tests.conftest import MakeSettings

URL = "http://127.0.0.1:7777/mcp"
UPLOAD = "http://127.0.0.1:7777/api/v1/knowledge-uploads/abc"
INIT = {
    "protocolVersion": "2025-06-18",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "Meko", "version": "1.20261116.0"},
}


class Server:
    """A scripted Meko: `answers[tool]` is what each tool returns; every request is kept."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.tools: list[tuple[str, dict[str, Any]]] = []
        self.uploads: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) != URL:
            self.uploads.append(request)
            return httpx.Response(204)
        if request.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            result: dict[str, Any] = INIT
        else:
            name, arguments = body["params"]["name"], body["params"]["arguments"]
            self.tools.append((name, arguments))
            result = {"content": [{"type": "text", "text": json.dumps(self.answers[name])}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


@pytest.fixture
def log() -> MemoryCallLog:
    return MemoryCallLog()


async def _meko(
    server: Server, log: MemoryCallLog, *, target: str = "local", ceiling: int = 0, **kw: Any
) -> AsyncIterator[McpMeko]:
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(server)) as http,
        MekoMcpSession(http, URL, SecretStr("mko_tkn_secret"), max_tool_calls=20) as session,
    ):
        yield McpMeko(session, Quota(log, target, ceiling), http, **kw)  # type: ignore[arg-type]


async def test_conversations_and_turns(log: MemoryCallLog) -> None:
    server = Server(
        {
            "conversation_create": {"id": "c1", "title": "Session 4"},
            "conversation_add_message": {"status": "accepted", "message_id": "m1"},
            "conversation_delete": {"message": "deleted"},
        }
    )
    async for meko in _meko(server, log, datapack_id="dp-1"):
        conversation = await meko.create_conversation(
            agent_id="kako:orchestrator", title="Session 4", session_key="session-4"
        )
        turn = Turn(
            input="Mara has a new job.",
            output="Noted. I'll propose the new salary.",
            plan=("Read what changed", "Propose the replacement"),
            reasoning="A salary change replaces a fact.",
            metadata={"kako_turn": 2},
            seed="session-4:turn-2",
        )
        assert await meko.add_turn(conversation, turn, agent_id="kako:orchestrator") == "m1"
        await meko.delete_conversation(conversation, agent_id="kako:orchestrator")
    assert server.tools == [
        ("conversation_create", {
            "title": "Session 4", "session_id": "session-4",
            "agent_id": "kako:orchestrator", "datapack_id": "dp-1",
        }),
        ("conversation_add_message", {
            "conversation_id": "c1", "input": "Mara has a new job.",
            "output": "Noted. I'll propose the new salary.",
            "plan": ["Read what changed", "Propose the replacement"],
            "reasoning": "A salary change replaces a fact.", "metadata": '{"kako_turn": 2}',
            "seed": "session-4:turn-2", "agent_id": "kako:orchestrator", "datapack_id": "dp-1",
        }),
        ("conversation_delete", {
            "conversation_id": "c1", "agent_id": "kako:orchestrator", "datapack_id": "dp-1",
        }),
    ]  # fmt: skip
    assert [(c.tool, c.outcome) for c in log.calls] == [
        ("conversation_create", "ok"),
        ("conversation_add_message", "ok"),
        ("conversation_delete", "ok"),
    ]


async def test_memories_and_searches(log: MemoryCallLog) -> None:
    memory = {
        "id": "mem-1",
        "memory": "Mara Villanueva's take-home pay is ₱68,000 a month from Dec 1, 2026.",
        "metadata": {"kako_source": "approved_fact", "fact_id": "f-1"},
        "score": 0.64,
    }
    chunk = {
        "id": "k-1",
        "document_id": "doc-1",
        "chunk_text": "SSS contributions…",
        "rerank_score": 0.9,
    }
    server = Server(
        {
            "memory_add": {
                "results": [{"id": "mem-1", "memory": memory["memory"], "event": "ADD"}]
            },
            "memory_update": {"message": "updated"},
            "memory_delete_by_id": {"message": "Memory deleted successfully!"},
            "context_search": {
                "results": {
                    "memory": [memory],
                    "knowledge_base": [chunk],
                    "conversation": {"hits": [], "thread": []},
                }
            },
            "knowledgebase_search": {"results": [chunk], "count": 1},
        }
    )
    async for meko in _meko(server, log):
        memory_id = await meko.add_memory(
            "c1", str(memory["memory"]), {"kako_source": "approved_fact"}, agent_id="kako:dreaming"
        )
        assert memory_id == "mem-1"
        await meko.update_memory("c1", memory_id, "Until Nov 30, 2026, …", agent_id="kako:dreaming")
        context = await meko.search_context("c1", "Mara's pay", agent_id="kako:budget", limit=3)
        assert context.memories[0].id == "mem-1"
        assert context.memories[0].metadata["fact_id"] == "f-1"
        assert context.memories[0].score == pytest.approx(0.64)
        assert context.knowledge[0].document_id == "doc-1"
        assert context.knowledge[0].score == pytest.approx(0.9)
        hits = await meko.search_knowledge("c1", "SSS", agent_id="kako:budget")
        assert [h.text for h in hits] == ["SSS contributions…"]
        await meko.delete_memory("c1", memory_id, agent_id="kako:dreaming")
        with pytest.raises(MekoError, match="1 to 50"):
            await meko.search_context("c1", "anything", agent_id="kako:budget", limit=0)
    sent = dict(server.tools)
    assert sent["memory_add"]["metadata"] == '{"kako_source": "approved_fact"}'
    assert sent["knowledgebase_search"]["datapack_id"] == ""  # the tool requires it: the default
    assert "datapack_id" not in sent["memory_add"]
    # Searches log how many results came back.
    assert [(c.tool, c.result_count) for c in log.calls if c.tool.endswith("search")] == [
        ("context_search", 2),
        ("knowledgebase_search", 1),
    ]


async def test_a_document_is_posted_to_its_link_without_the_api_key(log: MemoryCallLog) -> None:
    server = Server(
        {
            "knowledgebase_upload_document": {
                "url": UPLOAD,
                "fields": {"key": "u/d/hash/sss.md"},
                "key": "u/d/hash/sss.md",
                "already_uploaded": False,
            },
            "knowledgebase_document_status": {
                "state": "completed",
                "filename": "sss.md",
                "document_id": "doc-1",
                "message": "The file is indexed and searchable.",
            },
            "knowledgebase_delete_document": {"document_id": "doc-1", "chunks_deleted": 1},
        }
    )
    content = b"# SSS\n\nPlain-language reference.\n"
    async for meko in _meko(server, log):
        document = await meko.upload_document("c1", "sss.md", content, agent_id="kako:seed")
        assert (document.key, document.state, document.already_uploaded) == (
            "u/d/hash/sss.md",
            "indexing",
            False,
        )
        status = await meko.document_status("c1", document.key, agent_id="kako:seed")
        assert (status.state, status.document_id) == ("completed", "doc-1")
        await meko.delete_document("c1", "doc-1", agent_id="kako:seed")
    (upload,) = server.uploads
    assert upload.method == "POST"
    assert "authorization" not in upload.headers
    assert b'name="key"' in upload.content
    assert content in upload.content
    asked = dict(server.tools)["knowledgebase_upload_document"]
    assert asked["size"] == len(content)
    assert len(asked["content_hash"]) == 64
    assert "agent_id" not in dict(server.tools)["knowledgebase_delete_document"]


async def test_an_uploaded_file_is_not_posted_again(log: MemoryCallLog) -> None:
    server = Server(
        {"knowledgebase_upload_document": {"url": "", "key": "k", "already_uploaded": True}}
    )
    async for meko in _meko(server, log):
        document = await meko.upload_document("c1", "sss.md", b"x", agent_id="kako:seed")
    assert document.already_uploaded
    assert server.uploads == []


@pytest.mark.parametrize(
    ("url", "message"),
    [("http://uploads.example.com/x", "must use https"), ("ftp://127.0.0.1/x", "isn't an http")],
)
async def test_an_unsafe_upload_link_is_refused(log: MemoryCallLog, url: str, message: str) -> None:
    server = Server({"knowledgebase_upload_document": {"url": url, "fields": {}, "key": "k"}})
    async for meko in _meko(server, log):
        with pytest.raises(MekoError, match=message):
            await meko.upload_document("c1", "sss.md", b"x", agent_id="kako:seed")
    assert server.uploads == []


async def test_what_is_refused_before_anything_is_sent(log: MemoryCallLog) -> None:
    server = Server({"context_search": {"results": {}}})
    async for meko in _meko(server, log, target="cloud", ceiling=0):
        with pytest.raises(MekoError, match="kako:<role>"):
            await meko.search_context("c1", "q", agent_id="orchestrator")
        with pytest.raises(MekoError, match=r"doesn't take \.exe"):
            await meko.upload_document("c1", "run.exe", b"x", agent_id="kako:seed")
        with pytest.raises(MekoError, match="empty"):
            await meko.upload_document("c1", "a.md", b"", agent_id="kako:seed")
        with pytest.raises(MekoQuotaError):
            await meko.search_context("c1", "q", agent_id="kako:orchestrator")
    assert server.tools == []
    assert [(c.tool, c.outcome) for c in log.calls] == [("context_search", "refused")]


async def test_an_answer_out_of_shape_is_a_protocol_error(log: MemoryCallLog) -> None:
    server = Server({"memory_add": {"results": []}, "context_search": {"results": []}})
    async for meko in _meko(server, log):
        with pytest.raises(MekoProtocolError, match="memory_add"):
            await meko.add_memory("c1", "x", {}, agent_id="kako:dreaming")
        with pytest.raises(MekoProtocolError, match="context_search"):
            await meko.search_context("c1", "x", agent_id="kako:dreaming")
    # Meko answered, so both calls were made and count; the answer's shape is Kako's problem.
    assert [(c.tool, c.outcome) for c in log.calls] == [
        ("memory_add", "ok"),
        ("context_search", "ok"),
    ]


def test_agent_ids() -> None:
    assert check_agent_id("kako:orchestrator") == "kako:orchestrator"
    assert check_agent_id("kako:ci-smoke") == "kako:ci-smoke"
    for bad in ("claude_code", "kako:", "kako:Debt", "meko_agent", "kako:debt "):
        with pytest.raises(MekoError):
            check_agent_id(bad)


async def test_the_fake_keeps_what_meko_keeps() -> None:
    meko = FakeMeko()
    c = await meko.create_conversation(agent_id="kako:orchestrator", title="t", session_key="s")
    assert (
        await meko.create_conversation(agent_id="kako:orchestrator", title="t", session_key="s")
        == c
    )
    turn = Turn("in", "out", seed="t1")
    await meko.add_turn(c, turn, agent_id="kako:orchestrator")
    await meko.add_turn(c, turn, agent_id="kako:orchestrator")  # the same seed: stored once
    assert meko.conversations[c].turns == [turn]
    assert await meko.read_turns(c, agent_id="kako:orchestrator") == [Turn("in", "out")]
    m = await meko.add_memory(c, "Mara Villanueva's take-home pay is ₱68,000.", {"fact_id": "f"},
                              agent_id="kako:dreaming")  # fmt: skip
    found = await meko.search_context(c, "Mara take-home pay", agent_id="kako:budget")
    assert [x.id for x in found.memories] == [m]
    with pytest.raises(MekoToolError, match="only the agent that wrote it"):
        await meko.update_memory(c, m, "x", agent_id="kako:budget")
    await meko.update_memory(
        c, m, "Until Nov 30, Mara's pay was ₱52,000.", agent_id="kako:dreaming"
    )
    await meko.delete_memory(c, m, agent_id="kako:dreaming")
    assert (await meko.search_context(c, "Mara pay", agent_id="kako:budget")).memories == ()
    with pytest.raises(MekoToolError, match="not found"):
        await meko.add_memory("nope", "x", {}, agent_id="kako:dreaming")
    with pytest.raises(MekoToolError, match="only its creator"):
        await meko.delete_conversation(c, agent_id="kako:budget")
    assert meko.calls[0] == "conversation_create"
    assert len(meko.quota.log.calls) == len(meko.calls)  # type: ignore[attr-defined]


async def test_the_demo_documents_upload_once() -> None:
    demo = read_demo()
    meko = FakeMeko()
    c = await meko.create_conversation(agent_id="kako:seed", title="Demo knowledge base")
    first = await upload_demo_documents(meko, demo, c, sleep=_no_sleep)
    assert [d.filename for d in first] == [p.name for p in demo.documents]
    assert all(d.state == "completed" for d in first)
    assert not any(d.already_uploaded for d in first)
    again = await upload_demo_documents(meko, demo, c, sleep=_no_sleep)
    assert all(d.already_uploaded for d in again)
    assert len(meko.documents) == len(demo.documents)
    hits = await meko.search_knowledge(c, "13th month pay", agent_id="kako:budget")
    assert "13th" in hits[0].text
    assert hits[0].document_id is not None
    await meko.delete_document(c, hits[0].document_id, agent_id="kako:seed")
    assert len(meko.documents) == len(demo.documents) - 1


async def _no_sleep(_: float) -> None:
    return None


class _Stuck(FakeMeko):
    def __init__(self, state: str) -> None:
        super().__init__()
        self.state = state

    async def document_status(self, conversation_id: str, key: str, *, agent_id: str) -> Document:
        document = await super().document_status(conversation_id, key, agent_id=agent_id)
        return Document(key, document.filename, self.state, message="unreadable")  # type: ignore[arg-type]


async def test_a_document_meko_cannot_index_stops_the_upload() -> None:
    demo = read_demo()
    failed = _Stuck("failed")
    c = await failed.create_conversation(agent_id="kako:seed", title="kb")
    with pytest.raises(DemoUploadError, match=r"couldn't index .*: unreadable"):
        await upload_demo_documents(failed, demo, c, sleep=_no_sleep)

    stuck = _Stuck("indexing")
    c = await stuck.create_conversation(agent_id="kako:seed", title="kb")
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    with pytest.raises(DemoUploadError, match="wasn't indexed after 3 checks"):
        await upload_demo_documents(stuck, demo, c, checks=3, pause=0.5, sleep=sleep)
    assert pauses == [0.5, 0.5]  # bounded: three checks, two pauses between them


def test_the_trace_link(make_settings: MakeSettings) -> None:
    cloud = "https://mcp.mekodata.ai/mcp"
    assert make_settings(meko_mcp_url=cloud).meko_trace_url("c1") is None
    with_project = make_settings(meko_mcp_url=cloud, meko_langfuse_project_id="p 1")
    assert with_project.meko_trace_url("c1") == (
        "https://cloud.mekodata.ai/observe-hub?project=p+1&session=c1"
    )
    local = make_settings(meko_mcp_url=URL, meko_langfuse_project_id="p1")
    assert local.meko_trace_url("c1") is None
    assert make_settings().meko_cloud_ceiling == 0
    assert make_settings(meko_datapack_id="  ").meko_datapack_id is None


async def test_turns_read_back_with_their_trace(log: MemoryCallLog) -> None:
    kept = {
        "message_id": "m1",
        "input": "Mara here.",
        "output": "Two options.",
        "plan": ["Read the brief", "Asked the debt specialist"],
        "reasoning": "debt specialist: all on the card.",
        "metadata": {"kako_plan_id": "p1", "kako_turn": "t1"},
    }
    server = Server(
        {"conversation_get": {"id": "c1", "messages": [kept, {**kept, "metadata": '{"a": 1}'}]}}
    )
    async for meko in _meko(server, log):
        turns = await meko.read_turns("c1", agent_id="kako:orchestrator")
    assert turns == [
        Turn(
            "Mara here.",
            "Two options.",
            ("Read the brief", "Asked the debt specialist"),
            "debt specialist: all on the card.",
            {"kako_plan_id": "p1", "kako_turn": "t1"},
        ),
        Turn(
            "Mara here.",
            "Two options.",
            ("Read the brief", "Asked the debt specialist"),
            "debt specialist: all on the card.",
            {"a": 1},
        ),
    ]
    assert server.tools == [
        ("conversation_get", {
            "conversation_id": "c1", "include_messages": True, "agent_id": "kako:orchestrator",
        }),
    ]  # fmt: skip
    for broken in ({"id": "c1"}, {"messages": [{"metadata": "{not json"}]}, {"messages": ["x"]}):
        async for meko in _meko(Server({"conversation_get": broken}), log):
            with pytest.raises(MekoProtocolError):
                await meko.read_turns("c1", agent_id="kako:orchestrator")


async def test_a_conversations_memories_with_who_wrote_them(log: MemoryCallLog) -> None:
    found = {
        "id": "mem-2",
        "memory": "The user's take-home pay will be 68,000 pesos a month.",
        "metadata": {"meko_conversation_id": "c1"},
        "score": 0.68,
        "agent_id": "kako:orchestrator",
        "run_id": "c1",
    }
    server = Server({"memory_search": {"results": [found]}})
    async for meko in _meko(server, log):
        (memory,) = await meko.search_memories("c1", "my take-home pay", agent_id="kako:dreaming")
    assert (memory.id, memory.agent_id, memory.conversation_id) == (
        "mem-2",
        "kako:orchestrator",
        "c1",
    )
    ((tool, sent),) = server.tools
    assert (tool, sent["run_id"], sent["limit"]) == ("memory_search", "c1", 20)


async def test_the_fake_searches_one_conversations_memories() -> None:
    meko = FakeMeko()
    c = await meko.create_conversation(agent_id="kako:orchestrator", title="t")
    other = await meko.create_conversation(agent_id="kako:orchestrator", title="u")
    mine = await meko.add_memory(c, "Mara's pay is 68,000.", {}, agent_id="kako:orchestrator")
    await meko.add_memory(other, "Mara's pay is 52,000.", {}, agent_id="kako:orchestrator")
    (found,) = await meko.search_memories(c, "Mara's pay", agent_id="kako:dreaming")
    assert (found.id, found.agent_id, found.conversation_id) == (mine, "kako:orchestrator", c)
