"""Context Gaps (Phase 4, task 6), in memory: which weak searches become questions, the question,
the fake's search log and replay, and `McpMeko` reading Meko's self-learning answers from a scripted
server (nested and flat), with a Meko that has no self-learning tools said plainly."""

from __future__ import annotations

from typing import Any

import pytest

from kako.gaps.questions import MAX_QUERY, question, reason_of, worth_asking
from kako.meko.adapter import LoggedSearch, Replay, SelfLearningUnavailable
from kako.meko.client import MekoError, MekoProtocolError
from kako.meko.fake import FakeMeko, band_of
from kako.meko.quota import MemoryCallLog
from tests.test_meko_adapter import Server, _meko

AGENT = "kako:gaps"


def search(band: Any = "low", **kw: Any) -> LoggedSearch:
    return LoggedSearch(
        **{"log_id": "l1", "query": "Who looks after Lia?", "band": band, "score": 0.3, **kw}
    )


def test_only_a_shortfall_of_coverage_is_asked() -> None:
    assert worth_asking(search())  # no reason given: its band says it fell short
    assert worth_asking(search("mid", reason="partial_match"))
    assert worth_asking(search(reason="nothing_matched", category="coverage"))
    assert not worth_asking(search("high"))
    assert not worth_asking(search(query="   "))
    assert worth_asking(search(reason="below_floor"))
    for reason in ("vague_prompt", "stale_source", "source_not_searched", "source_error"):
        assert not worth_asking(search(reason=reason)), reason
    assert not worth_asking(search(reason="weak_match", category="prompt"))  # category decides


def test_the_question_is_written_by_code() -> None:
    assert question(search()) == (
        'Kako looked for "Who looks after Lia?" in what it knows about your household and found '
        "little to go on. Can you tell Kako about it?"
    )
    assert "found only part of an answer" in question(search("mid"))
    spread = question(search(query="Who\n\nlooks   after\tLia?"))
    assert '"Who looks after Lia?"' in spread
    long = question(search(query="x" * 2000))
    assert "x" * MAX_QUERY in long
    assert "x" * (MAX_QUERY + 1) not in long
    assert reason_of(search()) == "weak_match"
    assert reason_of(search("mid")) == "partial_match"
    assert reason_of(search(reason="nothing_matched")) == "nothing_matched"


def test_bands() -> None:
    assert [band_of(s) for s in (None, 0.0, 0.49, 0.5, 0.74, 0.75, 1.0)] == [
        "low", "low", "low", "mid", "mid", "high", "high",
    ]  # fmt: skip


async def test_the_fake_logs_each_search_and_replays_it() -> None:
    meko = FakeMeko()
    conversation = await meko.create_conversation(agent_id=AGENT, title="t")
    await meko.add_memory(conversation, "Mara's salary is ₱52,000 a month.", {}, agent_id=AGENT)
    await meko.search_context(conversation, "Who looks after Lia after school?", agent_id=AGENT)
    await meko.search_context(conversation, "Mara salary month", agent_id=AGENT)
    await meko.search_context(conversation, "Mara salary pension", agent_id=AGENT)
    (low,) = await meko.logged_searches(conversation, agent_id=AGENT, band="low")
    (mid,) = await meko.logged_searches(conversation, agent_id=AGENT, band="mid")
    assert (low.query, low.score, low.reason, low.category) == (
        "Who looks after Lia after school?",
        None,
        "weak_match",
        "coverage",
    )
    assert (mid.query, mid.band, mid.score) == ("Mara salary pension", "mid", 0.667)

    unchanged = await meko.replay_search(conversation, low.log_id, agent_id=AGENT)
    assert unchanged.outcome == "no_change"
    await meko.add_memory(
        conversation, "Lola Remy looks after Lia after school.", {}, agent_id=AGENT
    )
    better = await meko.replay_search(conversation, low.log_id, agent_id=AGENT)
    assert better == Replay("improved", "low", "high", None, 0.8, False, False)
    assert meko.calls.count("selflearning_verify") == 2

    meko.self_learning = False
    with pytest.raises(SelfLearningUnavailable):
        await meko.logged_searches(conversation, agent_id=AGENT, band="low")
    with pytest.raises(SelfLearningUnavailable):
        await meko.replay_search(conversation, low.log_id, agent_id=AGENT)


async def test_mcp_reads_the_search_log_nested_or_flat() -> None:
    log = MemoryCallLog()
    server = Server(
        {
            "selflearning_query_log": {
                "results": [
                    {
                        "log_id": "q-1",
                        "query": "Who looks after Lia?",
                        "band": "LOW",
                        "best_score": 0.31,
                        "reason": "weak_match",
                        "category": "coverage",
                    },
                    {"id": "q-2", "prompt": "SSS loan", "match_quality": "mid", "score": 0.6},
                ],
                "page": 1,
            },
            "selflearning_verify": {
                "outcome": "improved",
                "before": {"band": "low", "best_score": 0.31},
                "after": {"band": "high", "best_score": 0.82},
                "indexing": False,
            },
        }
    )
    async for meko in _meko(server, log, datapack_id="dp-1"):
        found = await meko.logged_searches("c1", agent_id=AGENT, band="low")
        assert found == (
            LoggedSearch("q-1", "Who looks after Lia?", "low", 0.31, "weak_match", "coverage"),
            LoggedSearch("q-2", "SSS loan", "mid", 0.6),
        )
        replay = await meko.replay_search("c1", "q-1", agent_id=AGENT)
        assert replay == Replay("improved", "low", "high", 0.31, 0.82, False, False)
        server.answers["selflearning_verify"] = {
            "outcome": "no_change",
            "band_before": "mid",
            "best_score_before": 0.6,
            "band_after": "mid",
            "best_score_after": 0.6,
            "indexing": True,
            "nothing_added_since_last_run": True,
        }
        flat = await meko.replay_search("c1", "q-2", agent_id=AGENT)
        assert flat == Replay("no_change", "mid", "mid", 0.6, 0.6, True, True)
    assert server.tools[:2] == [
        ("selflearning_query_log", {
            "conversation_id": "c1", "band": "low", "datapack_id": "dp-1",
        }),
        ("selflearning_verify", {
            "conversation_id": "c1", "log_id": "q-1", "datapack_id": "dp-1",
        }),
    ]  # fmt: skip
    assert [c.tool for c in log.calls] == ["selflearning_query_log"] + ["selflearning_verify"] * 2


async def test_mcp_reads_meko_clouds_own_answers() -> None:
    """The answers Meko Cloud gave on Nov 24 (docs/meko-setup.md), trimmed: the log under `rows`,
    a replay's sides as objects. Neither tool takes an `agent_id`: Meko Cloud refuses one."""
    log = MemoryCallLog()
    server = Server(
        {
            "selflearning_query_log": {
                "datapack_id": "dp-1",
                "band": "low",
                "last": "7d",
                "page": 1,
                "page_size": 10,
                "total": 1,
                "has_more": False,
                "rows": [
                    {
                        "id": "6b25c3a5-eed6-4263-813c-bd9c85a6cc35",
                        "searched_at": "2026-11-24T13:10:22.900266Z",
                        "query": "Who looks after Lia after school?",
                        "band": "low",
                        "best_score": 0.2971,
                        "best_source": "memory",
                        "result_count": 5,
                        "reason": "weak_match",
                        "category": "coverage",
                        "sub_type": "memory",
                        "todos": ["add_context"],
                        "agent_id": "kako:orchestrator",
                        "note": "The closest match is weak.",
                    }
                ],
            },
            "selflearning_verify": {
                "datapack_id": "dp-1",
                "test_prompt_id": "876dbab4-7dd9-4b19-bc4e-bf7fb49d0ba1",
                "query": "Who looks after Lia after school?",
                "before": {
                    "run_no": None,
                    "band": "low",
                    "best_score": 0.2971,
                    "source": "baseline",
                },
                "after": {"run_no": 1, "band": "low", "best_score": 0.2971},
                "outcome": "no_change",
                "change": None,
                "nothing_added_since_last_run": False,
                "indexing": False,
                "added_since_last_run": [],
                "hits_above_mid": 0,
                "top_results": [],
                "hint": "The band did not change.",
            },
        }
    )
    async for meko in _meko(server, log, datapack_id="dp-1"):
        (found,) = await meko.logged_searches("c1", agent_id=AGENT, band="low")
        assert found == LoggedSearch(
            "6b25c3a5-eed6-4263-813c-bd9c85a6cc35",
            "Who looks after Lia after school?",
            "low",
            0.2971,
            "weak_match",
            "coverage",
        )
        assert worth_asking(found)
        replay = await meko.replay_search("c1", found.log_id, agent_id=AGENT)
        assert replay == Replay("no_change", "low", "low", 0.2971, 0.2971, False, False)
    assert all("agent_id" not in arguments for _, arguments in server.tools)
    assert [(c.tool, c.agent_id) for c in log.calls] == [
        ("selflearning_query_log", AGENT),
        ("selflearning_verify", AGENT),
    ]


@pytest.mark.parametrize(
    ("tool", "answer"),
    [
        ("selflearning_query_log", {"page": 1}),  # no list
        ("selflearning_query_log", {"results": ["q-1"]}),
        ("selflearning_query_log", {"results": [{"log_id": "q", "query": "x"}]}),  # no band
        ("selflearning_query_log", {"results": [{"id": "q", "query": "x", "band": "great"}]}),
        (
            "selflearning_query_log",
            {"results": [{"id": "q", "query": "x", "band": "low", "score": 3}]},
        ),
        ("selflearning_verify", {"before": {}, "after": {}}),  # no outcome
        ("selflearning_verify", {"outcome": "better"}),
    ],
)
async def test_mcp_refuses_an_answer_it_cant_read(tool: str, answer: Any) -> None:
    server = Server({tool: answer})
    async for meko in _meko(server, MemoryCallLog()):
        call = (
            meko.replay_search("c1", "q-1", agent_id=AGENT)
            if tool == "selflearning_verify"
            else meko.logged_searches("c1", agent_id=AGENT, band="low")
        )
        with pytest.raises(MekoProtocolError):
            await call


class _NoSuchTool(Server):
    """A Meko that answers a JSON-RPC error for every self-learning tool, as local Meko does."""

    def __init__(self, message: str) -> None:
        super().__init__({})
        self.message = message

    def __call__(self, request: Any) -> Any:
        import json

        import httpx

        body = json.loads(request.content) if request.content else {}
        if body.get("method") == "tools/call":
            error = {"code": -32602, "message": self.message}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": error})
        return super().__call__(request)


@pytest.mark.parametrize("message", ['unknown tool "selflearning_query_log"', "Tool not found"])
async def test_a_meko_without_self_learning_says_so(message: str) -> None:
    async for meko in _meko(_NoSuchTool(message), MemoryCallLog()):
        with pytest.raises(SelfLearningUnavailable, match="Meko Cloud does"):
            await meko.logged_searches("c1", agent_id=AGENT, band="low")


async def test_another_error_stays_what_it_was() -> None:
    async for meko in _meko(_NoSuchTool("rate limited"), MemoryCallLog()):
        with pytest.raises(MekoError) as raised:
            await meko.replay_search("c1", "q-1", agent_id=AGENT)
        assert not isinstance(raised.value, SelfLearningUnavailable)
