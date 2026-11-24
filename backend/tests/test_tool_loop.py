"""The agents' tool loop: tools run in code, bounds kept in code, every tool call an agent step."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from kako.agents.chat import ToolSpec
from kako.agents.model_manager import ModelManager
from kako.agents.spend import MemoryLlmLog
from kako.agents.tool_loop import AgentRun, Tool, ToolInputError, ToolResult, run_agent
from kako.agents.turn import MemoryStepLog, TurnContext
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend, calls, says

OBJECT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}
RUN_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")


def figures_tool(seen: list[dict[str, Any]]) -> Tool:
    async def run(arguments: dict[str, Any]) -> ToolResult:
        seen.append(arguments)
        return ToolResult(json.dumps({"F1": "₱9,050.00"}), "1 figure")

    return Tool(ToolSpec("get_figures", "Read figures.", OBJECT), run)


async def what_if(arguments: dict[str, Any]) -> ToolResult:
    if arguments.get("amount") == "lots":
        raise ToolInputError("amount must be a figure reference or 'rest'")
    return ToolResult('{"run": "W1"}', "W1: card paid off in 9 months", calc_run_id=RUN_ID)


async def submit(arguments: dict[str, Any]) -> ToolResult:
    if not arguments.get("text"):
        raise ToolInputError("text is required")
    return ToolResult('{"ok": true}', "proposal received", value={"text": arguments["text"]})


TOOLS_SPEC = {
    "what_if": ToolSpec("run_what_if", "Try allocations.", OBJECT),
    "submit": ToolSpec("submit_proposal", "Your answer.", OBJECT),
}


def tools(seen: list[dict[str, Any]]) -> list[Tool]:
    return [
        figures_tool(seen),
        Tool(TOOLS_SPEC["what_if"], what_if),
        Tool(TOOLS_SPEC["submit"], submit, final=True, counted=False),
    ]


async def run(
    make_settings: MakeSettings, script: dict[str, Any], seen: list[dict[str, Any]] | None = None
) -> tuple[AgentRun, ScriptedBackend, TurnContext]:
    backend = ScriptedBackend(script)
    models = ModelManager(make_settings(model_fast="kako-fast"), backend, MemoryLlmLog())
    turn = models.turn("s2:t1", steps=MemoryStepLog())
    result = await run_agent(
        models,
        turn,
        agent="debt",
        path="debt#1",
        tier="fast",
        system="You are the debt specialist.",
        user="Brief.",
        tools=tools(seen if seen is not None else []),
        max_output_tokens=800,
    )
    return result, backend, turn


def steps(turn: TurnContext) -> list[tuple[int, str, str, str]]:
    log = turn.steps
    assert isinstance(log, MemoryStepLog)
    return [(s.seq, s.agent, s.tool, s.outcome) for s in log.steps]


async def test_tools_run_and_the_final_tool_answers(make_settings: MakeSettings) -> None:
    seen: list[dict[str, Any]] = []
    result, backend, turn = await run(
        make_settings,
        {
            "s2:t1/debt#1/1": calls(("get_figures", {"keys": ["F1"]}), ("run_what_if", {})),
            "s2:t1/debt#1/2": calls(("submit_proposal", {"text": "Option A"})),
        },
        seen,
    )
    assert result == AgentRun({"text": "Option A"}, "", 2, 2)
    assert seen == [{"keys": ["F1"]}]
    assert steps(turn) == [
        (1, "debt", "get_figures", "ok"),
        (2, "debt", "run_what_if", "ok"),
        (3, "debt", "submit_proposal", "ok"),
    ]
    log = turn.steps
    assert isinstance(log, MemoryStepLog)
    assert log.steps[1].calc_run_id == RUN_ID
    assert log.steps[1].result_summary == "W1: card paid off in 9 months"
    # The second call carries the tool results back, each answering its call.
    second = backend.requests[1][2]
    assert [m.role for m in second.messages] == ["system", "user", "assistant", "tool", "tool"]
    assert [m.tool_call_id for m in second.messages[3:]] == ["call_1", "call_2"]


async def test_a_plain_answer_ends_the_loop_without_an_answer(make_settings: MakeSettings) -> None:
    result, _, turn = await run(make_settings, {"s2:t1/debt#1/1": says("I can't tell.")})
    assert result == AgentRun(None, "I can't tell.", 0, 1)
    assert steps(turn) == []


async def test_refused_arguments_go_back_to_the_model(make_settings: MakeSettings) -> None:
    result, backend, turn = await run(
        make_settings,
        {
            "s2:t1/debt#1/1": calls(
                ("run_what_if", {"amount": "lots"}), ("no_such_tool", {}), ("get_figures", {})
            ),
            "s2:t1/debt#1/2": calls(("submit_proposal", {"text": ""})),
            "s2:t1/debt#1/3": calls(("submit_proposal", {"text": "B"})),
        },
    )
    assert result.answer == {"text": "B"}
    assert steps(turn) == [
        (1, "debt", "run_what_if", "error"),
        (2, "debt", "no_such_tool", "error"),
        (3, "debt", "get_figures", "ok"),
        (4, "debt", "submit_proposal", "error"),
        (5, "debt", "submit_proposal", "ok"),
    ]
    told = [m.content for m in backend.requests[1][2].messages if m.role == "tool"]
    assert json.loads(told[0] or "") == {"error": "amount must be a figure reference or 'rest'"}
    assert "no tool called no_such_tool" in (told[1] or "")


async def test_malformed_arguments_are_refused(make_settings: MakeSettings) -> None:
    from kako.agents.chat import ChatReply, ToolCall

    bad = ChatReply("scripted", "", (ToolCall("c1", "get_figures", "{not json"),), 10, 5)
    listed = ChatReply("scripted", "", (ToolCall("c2", "get_figures", "[1, 2]"),), 10, 5)
    result, _, turn = await run(
        make_settings,
        {"s2:t1/debt#1/1": bad, "s2:t1/debt#1/2": listed, "s2:t1/debt#1/3": says("done")},
    )
    assert result.answer is None
    assert [s[3] for s in steps(turn)] == ["error", "error"]


async def test_after_four_tool_calls_only_the_final_tool_is_offered(
    make_settings: MakeSettings,
) -> None:
    result, backend, turn = await run(
        make_settings,
        {
            "s2:t1/debt#1/1": calls(*[("get_figures", {})] * 3),
            # Two more asked at once: the first takes the fourth call, the second is refused.
            "s2:t1/debt#1/2": calls(("run_what_if", {}), ("get_figures", {})),
            "s2:t1/debt#1/3": calls(("submit_proposal", {"text": "A"})),
        },
    )
    assert result == AgentRun({"text": "A"}, "", 4, 3)
    assert [s[3] for s in steps(turn)] == ["ok", "ok", "ok", "ok", "error", "ok"]
    third = backend.requests[2][2]
    assert [t.name for t in third.tools] == ["submit_proposal"]
    assert third.tool_choice == "required"


async def test_a_tool_offered_no_longer_is_refused(make_settings: MakeSettings) -> None:
    result, _, turn = await run(
        make_settings,
        {
            "s2:t1/debt#1/1": calls(*[("get_figures", {})] * 4),
            "s2:t1/debt#1/2": calls(("run_what_if", {})),  # ignores that only submit is offered
            "s2:t1/debt#1/3": calls(("submit_proposal", {"text": "A"})),
        },
    )
    assert result.answer == {"text": "A"}
    assert steps(turn)[4] == (5, "debt", "run_what_if", "error")


async def test_model_calls_are_bounded(make_settings: MakeSettings) -> None:
    """A model that never submits stops after max_tool_calls + 2 calls."""
    script = {f"s2:t1/debt#1/{n}": calls(("submit_proposal", {"text": ""})) for n in range(1, 9)}
    result, backend, _ = await run(make_settings, script)
    assert result.answer is None
    assert result.model_calls == 6
    assert len(backend.requests) == 6


async def test_a_tool_failure_stops_the_turn(make_settings: MakeSettings) -> None:
    async def broken(_: dict[str, Any]) -> ToolResult:
        raise RuntimeError("the database went away")

    backend = ScriptedBackend({"t/x/1": calls(("get_figures", {}), ("broken", {}))})
    models = ModelManager(make_settings(model_fast="kako-fast"), backend, MemoryLlmLog())
    seen: list[dict[str, Any]] = []
    with pytest.raises(RuntimeError, match="database went away"):
        await run_agent(
            models,
            models.turn("t"),
            agent="budget",
            path="x",
            tier="fast",
            system="s",
            user="u",
            tools=[figures_tool(seen), Tool(ToolSpec("broken", "b", OBJECT), broken)],
            max_output_tokens=100,
        )
    assert seen == [{}]  # the other call still finished first


async def test_tool_names_must_be_unique(make_settings: MakeSettings) -> None:
    models = ModelManager(make_settings(), ScriptedBackend({}), MemoryLlmLog())
    with pytest.raises(ValueError, match="share a name"):
        await run_agent(
            models,
            models.turn("t"),
            agent="budget",
            path="x",
            tier="fast",
            system="s",
            user="u",
            tools=[figures_tool([]), figures_tool([])],
            max_output_tokens=100,
        )
