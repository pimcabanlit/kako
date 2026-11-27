"""The metrics page's figures (Phase 5, task 4): per-turn seconds, averages and worst cases, the
saved results it reads, the preference's effect, and Meko's `datapack_metrics` through the
adapter."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from kako.db.metrics_read import _proposed, group_of
from kako.evals.preference import (
    CITES_PREFERENCE,
    PREFERENCE,
    effect_json,
    preference_questions,
    read_preference_effect,
)
from kako.evals.questions import architecture_of, read_test_set, session_title
from kako.evals.results import (
    ResultsError,
    read_dreaming_run,
    read_test_set_run,
)
from kako.meko.adapter import DatapackMetrics, Holding
from kako.meko.client import MekoProtocolError, MekoToolError
from kako.meko.fake import FakeMeko
from kako.meko.quota import MemoryCallLog
from kako.metrics.turns import (
    Call,
    dollars,
    model_ms,
    seconds,
    share,
    spread,
    turn_figures,
    whole,
)
from tests.test_meko_adapter import Server, _meko

AGENT = "kako:metrics"


@pytest.fixture
def log() -> MemoryCallLog:
    return MemoryCallLog()


RESULTS = Path(__file__).resolve().parents[2] / "data" / "test-set" / "results"


def _call(agent: str, ms: int, *, cost: str = "0.01", replayed: bool = True) -> Call:
    return Call(agent, ms, 1_000, 100, 500, Decimal(cost), replayed)


def test_a_turns_seconds_count_the_slowest_specialist_of_each_round() -> None:
    """Session 2 as logged: the orchestrator asks debt and savings side by side (two calls each),
    then answers in five calls of its own. The specialists' round is as long as debt's 10.2 s."""
    calls = [
        _call("orchestrator", 5330),
        _call("debt", 5761),
        _call("savings", 5467),
        _call("savings", 4145),
        _call("debt", 4442),
        *(_call("orchestrator", ms) for ms in (2449, 4880, 2619, 2116, 3455)),
    ]
    assert model_ms(calls) == 5330 + (5761 + 4442) + 2449 + 4880 + 2619 + 2116 + 3455
    # Two rounds of specialists, each as long as its slowest; a trailing round counts too.
    rounds = [
        _call("orchestrator", 100),
        _call("budget", 300),
        _call("debt", 200),
        _call("orchestrator", 100),
        _call("goals", 50),
    ]
    assert model_ms(rounds) == 100 + 300 + 100 + 50
    assert model_ms([]) == 0


def test_a_turns_figures() -> None:
    session = uuid.uuid4()
    turn = turn_figures(
        session,
        "s2:t1",
        "Session 2",
        [_call("orchestrator", 1000, cost="0.020000"), _call("debt", 2000, cost="0.001500")],
        2430,
    )
    assert (turn.model_calls, turn.input_tokens, turn.output_tokens, turn.cached_tokens) == (
        2,
        2_000,
        200,
        1_000,
    )
    assert turn.tokens == 2_200
    assert turn.cost_usd == Decimal("0.021500")
    assert turn.model_ms == 3000
    assert turn.replayed
    assert turn.brief_tokens == 2430
    live = turn_figures(session, "t1", "x", [_call("orchestrator", 1, replayed=False)])
    assert not live.replayed
    assert not turn_figures(session, "t2", "x", []).replayed  # no calls: nothing replayed


def test_the_average_and_the_worst_case() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    turns = [
        turn_figures(a, "t1", "A", [_call("orchestrator", 1000)], 2000),
        turn_figures(b, "t1", "B", [_call("orchestrator", 3000)], None),
        turn_figures(c, "t1", "C", [_call("orchestrator", 3000)], 2500),
    ]
    ms = spread(turns, lambda t: t.model_ms)
    assert ms is not None
    assert ms.average == Decimal("7000") / 3
    assert (ms.worst, ms.worst_session_id, ms.worst_title) == (Decimal(3000), b, "B")  # the first
    brief = spread(turns, lambda t: t.brief_tokens)  # only the turns that kept it
    assert brief is not None
    assert (brief.average, brief.worst, brief.worst_title) == (Decimal(2250), 2500, "C")
    assert spread([], lambda t: t.model_ms) is None
    assert spread(turns[1:2], lambda t: t.brief_tokens) is None


def test_rounding_is_half_up() -> None:
    assert whole(Decimal("2.5")) == 3
    assert whole(Decimal("51027.5")) == 51028
    assert dollars(Decimal("0.0452455")) == Decimal("0.045246")
    assert seconds(Decimal("26650")) == Decimal("26.7")
    assert share(17, 17) == Decimal("100.0")
    assert share(2, 3) == Decimal("66.7")
    assert share(1, 0) is None


def test_test_set_sessions_are_told_apart_by_title() -> None:
    assert session_title("q10", "specialists") == "Agent test set q10 (specialists)"
    assert architecture_of(session_title("q10", "specialists")) == "specialists"
    assert architecture_of(session_title("q01", "single")) == "single"
    assert architecture_of("Session 2") is None
    assert architecture_of("Agent test set q10 (specialists) again") is None
    assert group_of("Session 4") == "household"
    assert group_of("Agent test set q21 (single)") == "single"


def test_what_a_dream_run_proposed() -> None:
    counts = {
        "proposals": {"new_fact": 2, "replace_fact": 1},
        "patterns": [{"attribute": "preference.debt_vs_flexibility"}],
        "promotions": ["a", "b"],
    }
    assert _proposed(counts) == 6
    assert _proposed({}) == 0
    assert _proposed({"proposals": {"new_fact": True}, "patterns": "x"}) == 0
    assert _proposed(None) == 0


def test_the_saved_test_set_runs() -> None:
    specialists = read_test_set_run("specialists")
    single = read_test_set_run("single")
    assert specialists is not None
    assert single is not None
    assert specialists.architecture == "specialists"
    assert specialists.questions == 22
    assert specialists.score == Decimal("1.0000")
    assert specialists.checks_passed == 102
    assert single.score == Decimal("0.9071")
    assert set(specialists.scores) == {f"q{n:02}" for n in range(1, 23)}
    assert read_dreaming_run() is not None


def test_a_saved_result_out_of_shape_is_refused(tmp_path: Path) -> None:
    assert read_test_set_run("specialists", tmp_path) is None  # not measured yet
    good = json.loads((RESULTS / "specialists.json").read_text(encoding="utf-8"))
    for broken, message in (
        ({**good, "score": "1.5"}, "score is over 1"),
        ({**good, "run_at": "2026-11-24T14:04:08"}, "no time zone"),
        ({**good, "model_calls": -1}, "model_calls isn't a count"),
        ({**good, "cost_usd": "NaN"}, "cost_usd isn't a number"),
        ({**good, "architecture": "single"}, "holds a run of single"),
    ):
        (tmp_path / "specialists.json").write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ResultsError, match=message):
            read_test_set_run("specialists", tmp_path)
    (tmp_path / "specialists.json").write_text("[1", encoding="utf-8")
    with pytest.raises(ResultsError, match="can't be read"):
        read_test_set_run("specialists", tmp_path)
    (tmp_path / "results.json").write_text(json.dumps({"passed": "yes"}), encoding="utf-8")
    with pytest.raises(ResultsError, match="passed"):
        read_dreaming_run(tmp_path / "results.json")


def test_the_preference_questions() -> None:
    chosen = preference_questions(read_test_set())
    assert [q.id for q in chosen] == ["q10", "q12", "q16", "q21"]
    assert all(PREFERENCE in q.expect.sources for q in chosen)


def _result(qid: str, checks: list[tuple[str, bool]], cost: str = "0.05") -> dict[str, Any]:
    return {
        "id": qid,
        "score": sum(p for _, p in checks) / len(checks),
        "model_calls": 3,
        "cost_usd": cost,
        "checks": [{"name": n, "passed": p} for n, p in checks],
    }


def _run(results: list[dict[str, Any]], at: str) -> dict[str, Any]:
    return {"run_at": at, "mode": "replay", "results": results}


def test_the_preferences_effect_with_and_without_its_citation() -> None:
    q10 = [("answered", True), ("states 16 months", False)]
    with_run = _run(
        [
            _result("q10", [*q10, (CITES_PREFERENCE, True)]),
            _result("q12", [("answered", True), (CITES_PREFERENCE, False)]),
            _result("q01", [("answered", True)]),  # not a preference question: left out
        ],
        "2026-11-24T14:04:08+00:00",
    )
    without_run = _run(
        [
            _result("q10", [*q10, (CITES_PREFERENCE, False)]),
            _result("q12", [("answered", True), (CITES_PREFERENCE, False)], cost="0.10"),
        ],
        "2026-11-25T02:36:01+00:00",
    )
    effect = effect_json(with_run, without_run, ["q10", "q12"])
    with_side, without_side = effect["with"], effect["without"]
    assert [(q["id"], q["score"], q["score_without_citation"], q["cites_preference"])
            for q in with_side["questions"]] == [
        ("q10", "0.6667", "0.5000", True),
        ("q12", "0.5000", "1.0000", False),
    ]  # fmt: skip
    assert (with_side["score"], with_side["score_without_citation"]) == ("0.5834", "0.7500")
    assert (without_side["score"], without_side["score_without_citation"]) == ("0.4167", "0.7500")
    assert (without_side["model_calls"], without_side["cost_usd"]) == (6, "0.15")
    assert with_side["run_at"] == "2026-11-24T14:04:08+00:00"


def test_a_preference_side_needs_every_question(tmp_path: Path) -> None:
    with_run = _run([_result("q10", [("answered", True)])], "2026-11-24T14:04:08+00:00")
    with pytest.raises(ResultsError, match="no result for q12"):
        effect_json(with_run, with_run, ["q10", "q12"])
    assert read_preference_effect(tmp_path / "preference.json") is None


def test_the_saved_preference_effect_reads_back() -> None:
    effect = read_preference_effect()
    assert effect is not None
    assert effect.preference == PREFERENCE
    assert [q.id for q in effect.questions] == ["q10", "q12", "q16", "q21"]
    assert effect.with_side.score == Decimal("0.8572")
    assert effect.without_side.score == Decimal("0.7072")
    assert effect.with_side.behaviour == Decimal("0.8750")
    assert effect.without_side.behaviour == Decimal("0.8750")
    assert all(q.cited_without is False for q in effect.questions)


METRICS = {
    "context_efficiency": {"saved_pct": 88, "tokens_saved": 903000, "tokens_sent": 124000},
    "context_relevance": {"high": 27, "low": 193, "mid": 178, "relevant_pct": 52},
    "context_size": {
        "tokens": 37458,
        "knowledge": {"count": 22, "tokens": 22000},
        "memories": {"count": 42, "tokens": 8400},
        "conversations": {"count": 47, "tokens": 7058},
    },
    "datapack_id": "dp-1",
    "datapack_name": "kako-demo",
    "days": 90,
    "searches": 47,
    "used_default": False,
}


async def test_mcp_reads_datapack_metrics(log: MemoryCallLog) -> None:
    """Local Meko's answer (Nov 25). The tool takes no `agent_id`; the call is counted."""
    server = Server({"datapack_metrics": METRICS})
    async for meko in _meko(server, log, datapack_id="dp-1"):
        found = await meko.datapack_metrics("c1", agent_id=AGENT)
    assert found == DatapackMetrics(
        datapack_id="dp-1",
        datapack_name="kako-demo",
        days=90,
        searches=47,
        context_tokens=37458,
        knowledge=Holding(22, 22000),
        memories=Holding(42, 8400),
        conversations=Holding(47, 7058),
        tokens_sent=124000,
        tokens_saved=903000,
        saved_pct=88,
        relevance_high=27,
        relevance_mid=178,
        relevance_low=193,
        relevant_pct=52,
    )
    assert server.tools == [
        ("datapack_metrics", {"conversation_id": "c1", "days": 0, "datapack_id": "dp-1"})
    ]
    assert [(c.tool, c.agent_id, c.outcome) for c in log.calls] == [
        ("datapack_metrics", AGENT, "ok")
    ]


async def test_datapack_metrics_before_any_search(log: MemoryCallLog) -> None:
    fresh = {"context_size": {"tokens": 0}, "days": 90, "searches": 0}
    async for meko in _meko(Server({"datapack_metrics": fresh}), log):
        found = await meko.datapack_metrics("c1", agent_id=AGENT, days=7)
    assert found.context_tokens == 0
    assert found.memories == Holding(0, 0)
    assert found.saved_pct is None
    assert found.relevant_pct is None


@pytest.mark.parametrize(
    ("answer", "error", "message"),
    [
        ({"error": "conversation_id_required"}, MekoToolError, "conversation_id_required"),
        ({"days": 90}, MekoProtocolError, "context size"),
        ({"context_size": {"tokens": -1}}, MekoProtocolError, "tokens"),
        (
            {"context_size": {"tokens": 1}, "context_relevance": {"relevant_pct": 140}},
            MekoProtocolError,
            "over 100",
        ),
        ({"context_size": {"tokens": 1, "memories": {"count": "x"}}}, MekoProtocolError, "count"),
    ],
)
async def test_datapack_metrics_out_of_shape(
    log: MemoryCallLog, answer: dict[str, Any], error: type[Exception], message: str
) -> None:
    async for meko in _meko(Server({"datapack_metrics": answer}), log):
        with pytest.raises(error, match=message):
            await meko.datapack_metrics("c1", agent_id=AGENT)


async def test_the_fake_measures_what_it_holds() -> None:
    meko = FakeMeko(datapack_id="dp-1")
    conversation = await meko.create_conversation(agent_id=AGENT, title="t")
    await meko.add_memory(conversation, "x" * 40, {}, agent_id=AGENT)
    found = await meko.datapack_metrics(conversation, agent_id=AGENT)
    assert found.memories == Holding(1, 10)
    assert found.context_tokens == 10
    assert meko.calls[-1] == "datapack_metrics"
