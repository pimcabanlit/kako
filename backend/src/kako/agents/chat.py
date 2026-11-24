"""What one model call sends and gets back, in plain values: no SDK types (REVIEW.md rule 10).

The model manager turns these into a Chat Completions request on Azure AI Foundry, or replays them
from a recording. Requests have a stable digest, so a recording can tell when the prompt it was
made for has changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Literal

Tier = Literal["strong", "fast"]
# Who made a call: the values of llm_call.agent (docs/data-model.md; kako.db.enums).
CallAgent = Literal["orchestrator", "budget", "debt", "savings", "goals", "dreaming", "system"]
Role = Literal["system", "user", "assistant", "tool"]
ToolChoice = Literal["auto", "required", "none"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]

TIERS: Final = ("strong", "fast")


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


@dataclass(frozen=True)
class ChatRequest:
    tier: Tier
    messages: tuple[Message, ...]
    max_output_tokens: int  # GPT-5 models spend hidden reasoning from this too
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: ToolChoice = "auto"

    def __post_init__(self) -> None:
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")
        if not self.messages:
            raise ValueError("a request needs at least one message")

    def text_length(self) -> int:
        """Characters the model reads: every message and tool definition."""
        size = sum(
            len(m.content or "") + sum(len(c.arguments) for c in m.tool_calls)
            for m in self.messages
        )
        return size + sum(len(json.dumps(t.parameters)) + len(t.description) for t in self.tools)

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
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "tool_calls": [_call_json(c) for c in m.tool_calls],
                "tool_call_id": m.tool_call_id,
            }
            for m in request.messages
        ],
    }


def reply_to_json(reply: ChatReply) -> dict[str, Any]:
    return {
        "deployment": reply.deployment,
        "text": reply.text,
        "tool_calls": [_call_json(c) for c in reply.tool_calls],
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
        "cached_tokens": reply.cached_tokens,
        "finish_reason": reply.finish_reason,
        "latency_ms": reply.latency_ms,
    }


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
    )


def estimate_tokens(characters: int) -> int:
    """A deliberately high token estimate for text of this length, with no tokenizer download:
    one token per 3 characters (English and pesos run nearer 4). Budgets check against it."""
    return -(-characters // 3)
