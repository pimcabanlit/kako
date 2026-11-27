"""What one model call sends and gets back, in plain values: no SDK types (REVIEW.md rule 10).

The model manager turns these into a Messages API request on Claude (the default provider) or a
Chat Completions request on Azure AI Foundry, or replays them from a recording. Requests have a
stable digest, so a recording can tell when the prompt it was made for has changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Literal

from kako.agents.prompt_registry import PromptVersion

Tier = Literal["strong", "fast"]
# Who made a call: the values of llm_call.agent (docs/data-model.md; kako.db.enums).
CallAgent = Literal["orchestrator", "budget", "debt", "savings", "goals", "dreaming", "system"]
Role = Literal["system", "user", "assistant", "tool"]
ToolChoice = Literal["auto", "required", "none"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
# A reply's content as the provider wrote it, as JSON values: Claude's thinking blocks (opaque,
# signed) with its text and tool calls in their order. Sent back unchanged with the next request
# of the same loop, as Claude requires; never read or shown. Empty for Foundry.
Block = dict[str, Any]

TIERS: Final = ("strong", "fast")


class ModelError(Exception):
    """A model call or the sign-in before it failed. `retryable`: the same call may pass if
    tried again (rate limit, timeout, connection, server error). `maybe_billed`: the request may
    have reached the model before it failed (a timeout or a lost connection), so it is charged at
    its worst case."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
        maybe_billed: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.maybe_billed = maybe_billed


@dataclass(frozen=True)
class ToolSpec:
    """A function the model may call. `parameters` is a JSON schema; with `strict`, every
    property is required and no others are allowed, so the model's arguments match it."""

    name: str
    description: str
    parameters: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: (
        str  # JSON text, as the model wrote it: parsed and checked by the tool, never trusted
    )


@dataclass(frozen=True)
class Message:
    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # for role "tool": the call this answers
    # An assistant message's content as the provider wrote it (`Block`), when it came from a
    # reply in this loop: sent instead of content and tool_calls, which say the same.
    blocks: tuple[Block, ...] = ()


@dataclass(frozen=True)
class ChatRequest:
    tier: Tier
    messages: tuple[Message, ...]
    max_output_tokens: int  # hidden reasoning (thinking) is spent from this too
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice = "auto"
    # The versions of the prompts the system message was built from: logged on `llm_call`, never
    # sent and not in the digest (the system message's text already is).
    prompts: tuple[PromptVersion, ...] = ()

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")
        if not self.messages:
            raise ValueError("a request needs at least one message")

    def estimated_input_tokens(self) -> int:
        """A high estimate of the input tokens: every message and tool definition, in UTF-8
        bytes (so non-Latin text and emoji count more), plus a fixed overhead for each."""
        size = sum(_message_bytes(m) for m in self.messages)
        size += sum(_bytes(t.name + t.description + json.dumps(t.parameters)) for t in self.tools)
        overhead = MESSAGE_OVERHEAD * len(self.messages) + TOOL_OVERHEAD * len(self.tools)
        return estimate_tokens(size) + overhead

    def digest(self) -> str:
        """SHA-256 of the request in a canonical form: the same request, the same digest."""
        return hashlib.sha256(canonical_json(request_to_json(self)).encode()).hexdigest()


@dataclass(frozen=True)
class ChatReply:
    deployment: str
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0  # includes hidden reasoning
    cached_tokens: int = 0  # part of input_tokens, billed at the cached price
    finish_reason: str = "stop"
    latency_ms: int = 0
    # Part of input_tokens written to the prompt cache, billed at the cache-write price (Claude).
    cache_write_tokens: int = 0
    blocks: tuple[Block, ...] = ()  # the reply as the provider wrote it, to send back

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _call_json(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "arguments": call.arguments}


def _call_from(raw: dict[str, Any]) -> ToolCall:
    return ToolCall(id=str(raw["id"]), name=str(raw["name"]), arguments=str(raw["arguments"]))


def request_to_json(request: ChatRequest) -> dict[str, Any]:
    return {
        "tier": request.tier,
        "max_output_tokens": request.max_output_tokens,
        "tool_choice": request.tool_choice,
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "strict": t.strict,
            }
            for t in request.tools
        ],
        "messages": [_message_json(m) for m in request.messages],
    }


def _message_json(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
        "tool_calls": [_call_json(c) for c in message.tool_calls],
        "tool_call_id": message.tool_call_id,
    }
    if message.blocks:  # only when present, so requests recorded before them keep their digest
        out["blocks"] = list(message.blocks)
    return out


def reply_to_json(reply: ChatReply) -> dict[str, Any]:
    out: dict[str, Any] = {
        "deployment": reply.deployment,
        "text": reply.text,
        "tool_calls": [_call_json(c) for c in reply.tool_calls],
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
        "cached_tokens": reply.cached_tokens,
        "finish_reason": reply.finish_reason,
        "latency_ms": reply.latency_ms,
    }
    if reply.cache_write_tokens:
        out["cache_write_tokens"] = reply.cache_write_tokens
    if reply.blocks:
        out["blocks"] = list(reply.blocks)
    return out


def reply_from_json(raw: dict[str, Any]) -> ChatReply:
    return ChatReply(
        deployment=str(raw["deployment"]),
        text=str(raw["text"]),
        tool_calls=tuple(_call_from(c) for c in raw.get("tool_calls", [])),
        input_tokens=int(raw["input_tokens"]),
        output_tokens=int(raw["output_tokens"]),
        cached_tokens=int(raw.get("cached_tokens", 0)),
        finish_reason=str(raw.get("finish_reason", "stop")),
        latency_ms=int(raw.get("latency_ms", 0)),
        cache_write_tokens=int(raw.get("cache_write_tokens", 0)),
        blocks=tuple(_block_from(b) for b in raw.get("blocks", [])),
    )


def _block_from(raw: Any) -> Block:
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        raise ValueError("a recorded content block must be an object with a type")
    return dict(raw)


MESSAGE_OVERHEAD: Final = 8  # tokens a message's role and framing take
TOOL_OVERHEAD: Final = 16  # and a tool definition's


def _bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _message_bytes(message: Message) -> int:
    if message.blocks:  # the same words and calls, with the thinking blocks besides
        return sum(_bytes(canonical_json(b)) for b in message.blocks)
    return _bytes(message.content or "") + sum(
        _bytes(c.name + c.arguments) for c in message.tool_calls
    )


def estimate_tokens(size: int) -> int:
    """A deliberately high token estimate for `size` bytes of UTF-8 text, with no tokenizer
    download: one token per 3 bytes (English runs nearer 4 characters a token). Budgets check
    against it."""
    return -(-size // 3)


def estimate_text_tokens(text: str) -> int:
    return estimate_tokens(_bytes(text))
