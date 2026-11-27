"""Claude as the models' provider, with a fake Anthropic API: no network, no key spent.

`ClaudeChat` (the agents' calls), `ClaudeBackend` and `check_models` on Claude, the request it
sends (system prompt cached, strict tools, tool choice auto, thinking blocks sent back unchanged,
tool results in one user turn), the reply it reads (tool calls, cache reads and writes, finish
reason), which errors may pass next time, and the cost of a call that writes the cache.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest

from kako.agents.chat import (
    ChatReply,
    ChatRequest,
    Message,
    ToolCall,
    ToolSpec,
    reply_from_json,
    reply_to_json,
    request_to_json,
)
from kako.agents.model_manager import (
    CLAUDE_BETAS,
    CheckLine,
    ClaudeBackend,
    ClaudeChat,
    ModelError,
    ModelManager,
    ModelReply,
    chat_backend,
    check_models,
    claude_messages,
)
from kako.agents.prompt_registry import SystemPrompt
from kako.agents.recorded import RecordingBackend
from kako.agents.spend import MemoryLlmLog, cost_usd
from kako.agents.tool_loop import Tool, ToolResult, run_agent
from kako.agents.turn import MemoryStepLog
from kako.settings import Settings
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend, calls

KEY = "sk-ant-test-not-a-real-key"
OBJECT: dict[str, Any] = {
    "type": "object",
    "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
    "required": ["keys"],
    "additionalProperties": False,
}
THINKING = {"type": "thinking", "thinking": "", "signature": "sig-1"}


@pytest.fixture
def claude(make_settings: MakeSettings) -> Settings:
    return make_settings(anthropic_api_key=KEY)


def message(content: list[dict[str, Any]], stop: str = "tool_use", **usage: int) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 200,
            "output_tokens": 90,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        | usage,
    }


TOOL_REPLY = message(
    [
        THINKING,
        {"type": "text", "text": " Reading the figures. "},
        {"type": "tool_use", "id": "toolu_1", "name": "get_figures", "input": {"keys": ["F1"]}},
    ],
    cache_creation_input_tokens=1000,
    cache_read_input_tokens=3000,
)


def _chat(settings: Settings, handler: Callable[[httpx2.Request], httpx2.Response]) -> ClaudeChat:
    return ClaudeChat(
        settings, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )


def _request(tool_choice: str = "auto") -> ChatRequest:
    earlier = ChatReply(
        "claude-haiku-5-5",
        "",
        (ToolCall("toolu_0", "get_facts", "{}"),),
        blocks=(THINKING, {"type": "tool_use", "id": "toolu_0", "name": "get_facts", "input": {}}),
    )
    return ChatRequest(
        "fast",
        (
            Message("system", "You are the debt specialist."),
            Message("user", "An earlier question."),
            Message("assistant", "An earlier answer."),
            Message("user", "Brief."),
            Message("assistant", None, earlier.tool_calls, blocks=earlier.blocks),
            Message("tool", '{"facts": []}', tool_call_id="toolu_0"),
            Message("user", "A note from code."),
        ),
        max_output_tokens=800,
        tools=(ToolSpec("get_figures", "Read figures.", OBJECT),),
        tool_choice=tool_choice,  # type: ignore[arg-type]
    )


async def test_claude_chat_sends_the_request_claude_expects(
    claude: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Claude Code's own variables are in the environment; Kako's calls never follow them.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.invalid")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-someone-elses")
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=TOOL_REPLY)

    # "required" (the tool loop at its limit) is sent as auto: Claude refuses forced tool use.
    await _chat(claude, handler).chat(_request("required"), deployment="claude-haiku-5-5", key="k")

    (sent,) = seen
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"
    assert sent.headers["authorization"] == f"Bearer {KEY}"  # Kako's key, not the environment's
    assert set(CLAUDE_BETAS) <= set(sent.headers["anthropic-beta"].split(","))
    body = json.loads(sent.content)
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == 800
    assert body["thinking"] == {
        "type": "adaptive",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert body["output_config"] == {"effort": "low"}
    assert body["cache_control"] == {"type": "ephemeral"}  # the turns after the system prompt
    assert body["system"] == [
        {
            "type": "text",
            "text": "You are the debt specialist.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert body["tool_choice"] == {"type": "auto"}
    assert body["tools"] == [
        {
            "name": "get_figures",
            "description": "Read figures.",
            "input_schema": OBJECT,
            "strict": True,
        }
    ]
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "An earlier question."}]},
        {"role": "assistant", "content": [{"type": "text", "text": "An earlier answer."}]},
        {"role": "user", "content": [{"type": "text", "text": "Brief."}]},
        # The reply as Claude wrote it, its thinking block unchanged.
        {
            "role": "assistant",
            "content": [
                THINKING,
                {"type": "tool_use", "id": "toolu_0", "name": "get_facts", "input": {}},
            ],
        },
        # Tool results first, then code's note, in one user turn.
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_0", "content": '{"facts": []}'},
                {"type": "text", "text": "A note from code."},
            ],
        },
    ]


async def test_claude_chat_reads_tool_calls_tokens_and_blocks(claude: Settings) -> None:
    reply = await _chat(claude, lambda _: httpx2.Response(200, json=TOOL_REPLY)).chat(
        _request(), deployment="claude-haiku-5-5", key="k"
    )
    assert reply.deployment == "claude-haiku-5-5"
    assert reply.text == "Reading the figures."
    assert reply.tool_calls == (ToolCall("toolu_1", "get_figures", '{"keys": ["F1"]}'),)
    assert reply.finish_reason == "tool_calls"
    # Every input token is counted: uncached, written to the cache, and read from it.
    assert (reply.input_tokens, reply.cached_tokens, reply.cache_write_tokens) == (4200, 3000, 1000)
    assert reply.output_tokens == 90
    assert reply.blocks == tuple(TOOL_REPLY["content"])


@pytest.mark.parametrize(
    ("stop", "finish"),
    [("end_turn", "stop"), ("max_tokens", "length"), ("refusal", "refusal")],
)
async def test_claude_chat_says_why_it_stopped(claude: Settings, stop: str, finish: str) -> None:
    body = message([{"type": "text", "text": "ok"}], stop=stop)
    reply = await _chat(claude, lambda _: httpx2.Response(200, json=body)).chat(
        ChatRequest("strong", (Message("user", "hi"),), max_output_tokens=16),
        deployment="claude-opus-5-5",
        key="k",
    )
    assert reply.finish_reason == finish
    assert reply.tool_calls == ()


async def test_claude_chat_sends_the_strong_tiers_effort(make_settings: MakeSettings) -> None:
    settings = make_settings(anthropic_api_key=KEY, claude_effort_strong="medium")
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=message([{"type": "text", "text": "ok"}], "end_turn"))

    request = ChatRequest("strong", (Message("user", "hi"),), max_output_tokens=16)
    await _chat(settings, handler).chat(request, deployment="claude-opus-5-5", key="k")
    assert seen[0]["output_config"] == {"effort": "medium"}
    assert "tools" not in seen[0]
    assert "system" not in seen[0]


@pytest.mark.parametrize(
    ("status", "headers", "retryable", "retry_after"),
    [
        (429, {"retry-after": "7"}, True, 7.0),
        (529, {}, True, None),  # overloaded
        (500, {}, True, None),
        (400, {}, False, None),
        (401, {}, False, None),
    ],
)
async def test_claude_chat_says_which_errors_may_pass_next_time(
    claude: Settings,
    status: int,
    headers: dict[str, str],
    retryable: bool,
    retry_after: float | None,
) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        error = {"type": "error", "error": {"type": "api_error", "message": "no"}}
        return httpx2.Response(status, headers=headers, json=error)

    request = ChatRequest("fast", (Message("user", "hi"),), max_output_tokens=16)
    with pytest.raises(ModelError) as caught:
        await _chat(claude, handler).chat(request, deployment="claude-haiku-5-5", key="k")
    assert caught.value.retryable is retryable
    assert caught.value.retry_after == retry_after
    assert KEY not in str(caught.value)


async def test_a_lost_connection_may_have_been_billed(claude: Settings) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection reset", request=request)

    request = ChatRequest("fast", (Message("user", "hi"),), max_output_tokens=16)
    with pytest.raises(ModelError) as caught:
        await _chat(claude, handler).chat(request, deployment="claude-haiku-5-5", key="k")
    assert caught.value.retryable
    assert caught.value.maybe_billed


def test_claude_needs_its_key_and_claude_models(make_settings: MakeSettings) -> None:
    with pytest.raises(ModelError, match="KAKO_ANTHROPIC_API_KEY is not set"):
        ClaudeChat(make_settings())
    with pytest.raises(ModelError, match=r"KAKO_MODEL_STRONG=gpt-5\.4 isn't a Claude model"):
        ClaudeChat(make_settings(anthropic_api_key=KEY, model_strong="gpt-5.4"))


def test_only_kakos_own_key_is_read(
    make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-claude-codes")
    assert make_settings().anthropic_api_key is None
    monkeypatch.setenv("KAKO_ANTHROPIC_API_KEY", KEY)
    settings = make_settings()
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == KEY
    assert KEY not in repr(settings)
    assert make_settings(anthropic_api_key="  ").anthropic_api_key is None


def test_the_provider_picks_the_live_backend(claude: Settings, tmp_path: Path) -> None:
    assert isinstance(chat_backend(claude), ClaudeChat)
    recording = chat_backend(
        claude.model_copy(
            update={"model_mode": "record", "recorded_responses": tmp_path / "r.json"}
        )
    )
    assert isinstance(recording, RecordingBackend)


def test_claude_messages_refuse_a_system_message_after_the_first() -> None:
    with pytest.raises(ModelError, match="must come first"):
        claude_messages((Message("user", "hi"), Message("system", "late")))
    # Tool calls from an earlier turn, with no blocks, are written out as Claude's blocks.
    _, turns = claude_messages(
        (Message("assistant", "Let me look.", (ToolCall("t1", "get_facts", '{"a": 1}'),)),)
    )
    assert turns == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                {"type": "tool_use", "id": "t1", "name": "get_facts", "input": {"a": 1}},
            ],
        }
    ]


def test_a_reply_with_blocks_is_recorded_and_read_back() -> None:
    reply = ChatReply(
        "claude-haiku-5-5",
        "",
        (ToolCall("toolu_1", "get_figures", "{}"),),
        100,
        20,
        60,
        "tool_calls",
        5,
        cache_write_tokens=30,
        blocks=(THINKING,),
    )
    assert reply_from_json(reply_to_json(reply)) == reply
    # A Foundry reply and message keep the shape they were recorded in, and so their digests.
    plain = reply_to_json(ChatReply("gpt-5.4", "ok"))
    assert "blocks" not in plain
    assert "cache_write_tokens" not in plain
    request = request_to_json(ChatRequest("fast", (Message("user", "hi"),), max_output_tokens=8))
    assert "blocks" not in request["messages"][0]
    with pytest.raises(ValueError, match="content block"):
        reply_from_json(reply_to_json(reply) | {"blocks": ["not a block"]})


async def test_the_tool_loop_sends_claudes_blocks_back() -> None:
    blocks = (THINKING, {"type": "tool_use", "id": "call_1", "name": "get_figures", "input": {}})
    first = calls(("get_figures", {}))
    first = ChatReply(first.deployment, "", first.tool_calls, 100, 20, blocks=blocks)
    backend = ScriptedBackend(
        {"t/debt#1/1": first, "t/debt#1/2": calls(("submit_proposal", {"text": "A"}))}
    )
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    models = ModelManager(settings, backend, MemoryLlmLog())
    turn = models.turn("t", steps=MemoryStepLog())

    async def figures(_: dict[str, Any]) -> ToolResult:
        return ToolResult("{}", "none")

    async def submit(arguments: dict[str, Any]) -> ToolResult:
        return ToolResult("{}", "ok", value=arguments)

    empty: dict[str, Any] = {"type": "object", "properties": {}}
    result = await run_agent(
        models,
        turn,
        agent="debt",
        path="debt#1",
        tier="fast",
        system=SystemPrompt("You are the debt specialist.", ()),
        user="Brief.",
        tools=[
            Tool(ToolSpec("get_figures", "Read.", empty), figures),
            Tool(ToolSpec("submit_proposal", "Answer.", empty), submit, final=True, counted=False),
        ],
        max_output_tokens=800,
    )
    assert result.answer == {"text": "A"}
    assistant = backend.requests[1][2].messages[2]
    assert assistant.role == "assistant"
    assert assistant.blocks == blocks


async def test_a_call_that_writes_the_cache_is_priced_for_it(claude: Settings) -> None:
    reply = ChatReply("claude-opus-5-5", "ok", (), 10_000, 100, 6_000, cache_write_tokens=3_000)
    backend = ScriptedBackend({"t/o/1": reply})
    log = MemoryLlmLog()
    models = ModelManager(claude, backend, log)
    request = ChatRequest("strong", (Message("user", "hi"),), max_output_tokens=100)
    await models.chat(request, turn=models.turn("t"), agent="orchestrator", key="t/o/1")
    (record,) = log.records
    # 1,000 uncached x 4 + 6,000 read x 0.20 + 3,000 written x 5 + 100 out x 20 = 22,200 / 1M
    assert record.cost_usd == Decimal("0.022200")
    assert cost_usd(
        (Decimal(4), Decimal("0.2"), Decimal(20)),
        10_000,
        6_000,
        100,
        cache_write_tokens=3_000,
        cache_write_price=Decimal(5),
    ) == Decimal("0.022200")


# ---------------------------------------------------------------------------------------------
# check-models on Claude
# ---------------------------------------------------------------------------------------------


class FakeClaude:
    def __init__(self, *, sign_in_fails: bool = False, failing: set[str] | None = None) -> None:
        self.sign_in_fails = sign_in_fails
        self.failing = failing or set()
        self.calls: list[tuple[str, int]] = []

    def sign_in(self, model: str) -> str:
        if self.sign_in_fails:
            raise ModelError("AuthenticationError: invalid x-api-key")
        return "Claude Opus 5.5"

    def complete(self, deployment: str, prompt: str, max_output_tokens: int) -> ModelReply:
        self.calls.append((deployment, max_output_tokens))
        if deployment in self.failing:
            raise ModelError("NotFoundError: model not found")
        return ModelReply(deployment, "OK", 12, 40, 300)


def check(settings: Settings, fake: FakeClaude) -> list[CheckLine]:
    return check_models(settings, claude_factory=lambda _: fake)


def test_check_models_on_claude_calls_each_model_once(claude: Settings) -> None:
    fake = FakeClaude()
    lines = check(claude, fake)
    assert all(line.ok for line in lines), lines
    assert [line.label for line in lines] == [
        "Settings",
        "Sign-in",
        "Model claude-opus-5-5 (strong)",
        "Model claude-haiku-5-5 (fast)",
    ]
    assert lines[0].detail.startswith("Claude at https://api.anthropic.com")
    assert fake.calls == [("claude-opus-5-5", 256), ("claude-haiku-5-5", 256)]
    assert KEY not in "".join(str(line) for line in lines)


def test_check_models_on_claude_stops_on_settings_and_sign_in(
    make_settings: MakeSettings,
) -> None:
    fake = FakeClaude()
    assert [str(line) for line in check(make_settings(), fake)] == [
        "[FAIL] Settings: missing KAKO_ANTHROPIC_API_KEY"
    ]
    lines = check(make_settings(anthropic_api_key=KEY, model_fast="gpt-5-mini"), fake)
    assert "KAKO_MODEL_FAST=gpt-5-mini isn't a Claude model" in lines[0].detail
    lines = check(make_settings(anthropic_api_key=KEY), FakeClaude(sign_in_fails=True))
    assert [line.ok for line in lines] == [True, False]
    assert "invalid x-api-key" in lines[-1].detail
    assert fake.calls == []


def test_check_models_on_claude_fails_only_the_failing_models_line(claude: Settings) -> None:
    lines = check(claude, FakeClaude(failing={"claude-haiku-5-5"}))
    assert [line.ok for line in lines] == [True, True, True, False]


def test_claude_backend_signs_in_then_makes_a_tiny_call(claude: Settings) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path.startswith("/v1/models/"):
            return httpx2.Response(
                200,
                json={
                    "type": "model",
                    "id": "claude-opus-5-5",
                    "display_name": "Claude Opus 5.5",
                    "created_at": "2026-10-01T00:00:00Z",
                },
            )
        return httpx2.Response(200, json=message([{"type": "text", "text": "OK"}], "end_turn"))

    backend = ClaudeBackend(
        claude, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    assert backend.sign_in("claude-opus-5-5") == "Claude Opus 5.5"
    reply = backend.complete("claude-opus-5-5", "Reply with the single word OK.", 256)
    assert (reply.text, reply.input_tokens, reply.output_tokens) == ("OK", 200, 90)
    body = json.loads(seen[1].content)
    assert body["thinking"]["type"] == "adaptive"  # the same shape as an agent's call
    assert all(r.headers["authorization"] == f"Bearer {KEY}" for r in seen)
