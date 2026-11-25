"""Recorded responses: a turn recorded once replays with no network (Phase 3, task 1, done when:
recorded responses replay a turn with no network). A scripted model stands in for Foundry while
recording, so no test spends money."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from kako.agents.chat import ChatReply, ChatRequest, Message, ToolSpec
from kako.agents.model_manager import ModelManager
from kako.agents.prompt_registry import SystemPrompt
from kako.agents.recorded import (
    ChatBackend,
    RecordedCall,
    RecordingBackend,
    RecordingError,
    ReplayBackend,
    read_recording,
    write_recording,
)
from kako.agents.spend import MemoryLlmLog
from kako.agents.tool_loop import AgentRun, Tool, ToolResult, run_agent
from kako.agents.turn import MemoryStepLog
from kako.settings import Settings
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend, calls, says

OBJECT: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
    "additionalProperties": False,
}
SEED = "session-2:turn-1"
SCRIPT = {
    f"{SEED}/orchestrator/1": calls(("ask_debt", {"question": "How hard on the card?"})),
    f"{SEED}/debt#1/1": calls(("get_figures", {"question": "surplus"})),
    f"{SEED}/debt#1/2": says("Option A puts the whole surplus on the card.", tokens=(900, 60)),
    f"{SEED}/orchestrator/2": says("Here are options A and B.", tokens=(1_500, 80)),
}


async def a_turn(settings: Settings, backend: ChatBackend) -> tuple[AgentRun, ModelManager, Any]:
    """An orchestrator that asks the debt specialist, who reads a figure: two agents, four calls."""
    log = MemoryLlmLog()
    models = ModelManager(settings, backend, log)
    turn = models.turn(SEED, steps=MemoryStepLog())

    async def get_figures(_: dict[str, Any]) -> ToolResult:
        return ToolResult('{"F1": "₱9,050.00"}', "1 figure")

    async def ask_debt(arguments: dict[str, Any]) -> ToolResult:
        answer = await run_agent(
            models,
            turn,
            agent="debt",
            path="debt#1",
            tier="fast",
            system=SystemPrompt("You are the debt specialist."),
            user=arguments["question"],
            tools=[Tool(ToolSpec("get_figures", "Read figures.", OBJECT), get_figures)],
            max_output_tokens=800,
        )
        return ToolResult(json.dumps({"debt": answer.text}), answer.text)

    result = await run_agent(
        models,
        turn,
        agent="orchestrator",
        path="orchestrator",
        tier="strong",
        system=SystemPrompt("You are the orchestrator."),
        user="How hard should we pay down the card?",
        tools=[Tool(ToolSpec("ask_debt", "Ask the debt specialist.", OBJECT), ask_debt)],
        max_output_tokens=2_000,
    )
    return result, models, log


async def test_a_recorded_turn_replays_with_no_network(
    make_settings: MakeSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "session-2.json"
    live = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    recorded, _, recorded_log = await a_turn(live, RecordingBackend(ScriptedBackend(SCRIPT), path))
    assert sorted(read_recording(path)) == sorted(SCRIPT)
    assert not any(r.recorded_replay for r in recorded_log.records)

    # Replay: no deployments, no Foundry endpoint, and no socket may open.
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a replay tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    replay = make_settings(model_mode="replay", recorded_responses=path)
    replayed, models, log = await a_turn(replay, ReplayBackend(path))

    assert replayed == recorded
    assert replayed.text == "Here are options A and B."
    assert models.replays
    assert [(r.agent, r.recorded_replay) for r in log.records] == [
        ("orchestrator", True),
        ("debt", True),
        ("debt", True),
        ("orchestrator", True),
    ]


async def test_a_changed_prompt_is_refused_unless_lenient(
    make_settings: MakeSettings, tmp_path: Path
) -> None:
    path = tmp_path / "r.json"
    request = ChatRequest("fast", (Message("user", "How hard?"),), max_output_tokens=100)
    write_recording(
        path, {"k": RecordedCall("k", request.digest(), ChatReply("gpt-5-mini", "Recorded."))}
    )
    changed = ChatRequest("fast", (Message("user", "How hard, now?"),), max_output_tokens=100)

    strict = ReplayBackend(path)
    assert (await strict.chat(request, deployment="(fast)", key="k")).text == "Recorded."
    with pytest.raises(RecordingError, match="has changed since it was recorded"):
        await strict.chat(changed, deployment="(fast)", key="k")
    with pytest.raises(RecordingError, match="no recorded call 'other'"):
        await strict.chat(request, deployment="(fast)", key="other")

    lenient = ReplayBackend(path, strict=False)
    assert (await lenient.chat(changed, deployment="(fast)", key="k")).text == "Recorded."
    assert lenient.drifted == ["k"]


def test_the_digest_covers_tools_and_limits() -> None:
    base = ChatRequest("fast", (Message("user", "hi"),), max_output_tokens=100)
    with_tool = ChatRequest(
        "fast", base.messages, 100, tools=(ToolSpec("get_figures", "Read.", OBJECT),)
    )
    stronger = ChatRequest("strong", base.messages, 100)
    longer = ChatRequest("fast", base.messages, 101)
    digests = {base.digest(), with_tool.digest(), stronger.digest(), longer.digest()}
    assert len(digests) == 4
    assert base.digest() == ChatRequest("fast", (Message("user", "hi"),), 100).digest()


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("not json", "isn't JSON"),
        ('{"format": 2, "calls": []}', "isn't a recording"),
        ('{"format": 1, "calls": [{"key": "k"}]}', "malformed"),
    ],
)
def test_a_bad_recording_is_refused(tmp_path: Path, content: str, error: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(RecordingError, match=error):
        read_recording(path)


def test_a_key_recorded_twice_is_refused(tmp_path: Path) -> None:
    call = {
        "key": "k",
        "request_sha256": "0" * 64,
        "reply": {"deployment": "d", "text": "t", "input_tokens": 1, "output_tokens": 1},
    }
    path = tmp_path / "twice.json"
    path.write_text(json.dumps({"format": 1, "calls": [call, call]}), encoding="utf-8")
    with pytest.raises(RecordingError, match="recorded twice"):
        read_recording(path)


def test_recording_needs_a_live_backend(tmp_path: Path) -> None:
    write_recording(tmp_path / "r.json", {})
    with pytest.raises(RecordingError, match="live backend"):
        RecordingBackend(ReplayBackend(tmp_path / "r.json"), tmp_path / "again.json")
