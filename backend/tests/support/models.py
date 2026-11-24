"""A scripted model for tests: replies chosen by call key, no network, no Azure.

Each key (`<turn seed>/<agent path>/<n>`) maps to a reply, or to a `ModelError` to raise, or to a
list of them for successive attempts at the same key (a retry). Every request is kept, so a test
can check what the model was sent.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from kako.agents.chat import ChatReply, ChatRequest, ToolCall
from kako.agents.model_manager import ModelError

Script = ChatReply | ModelError | Sequence[ChatReply | ModelError]


def says(text: str, *, tokens: tuple[int, int] = (100, 20), cached: int = 0) -> ChatReply:
    """A plain answer."""
    return ChatReply("scripted", text, (), tokens[0], tokens[1], cached)


def calls(
    *tool_calls: tuple[str, dict[str, Any]], tokens: tuple[int, int] = (100, 20)
) -> ChatReply:
    """A reply that asks for tools, each `(name, arguments)`."""
    return ChatReply(
        "scripted",
        "",
        tuple(
            ToolCall(f"call_{i}", name, json.dumps(arguments))
            for i, (name, arguments) in enumerate(tool_calls, start=1)
        ),
        tokens[0],
        tokens[1],
    )


class ScriptedBackend:
    def __init__(self, script: dict[str, Script], *, replays: bool = False) -> None:
        self._script = {
            key: list(value) if isinstance(value, Sequence) else [value]
            for key, value in script.items()
        }
        self._replays = replays
        self.requests: list[tuple[str, str, ChatRequest]] = []  # (key, deployment, request)

    @property
    def replays(self) -> bool:
        return self._replays

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        self.requests.append((key, deployment, request))
        queue = self._script.get(key)
        if not queue:
            raise AssertionError(f"the script has no reply for {key!r}")
        step = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(step, ModelError):
            raise step
        return step

    def keys(self) -> list[str]:
        return [key for key, _, _ in self.requests]
