"""Recorded model responses: tests, CI and demo mode replay them instead of calling Foundry.

A recording is one JSON file of calls, each under a **key** the caller names (such as
`session-2:turn-1/debt#1/2`: the turn, the agent and which of its calls). Keys rather than request
hashes, so a turn replays in the same order on any machine; each call also keeps the SHA-256 of the
request it answered, and a strict replay refuses a reply whose request has changed (the prompt or
the brief moved on since it was recorded: record it again).

`RecordingBackend` wraps a live backend and saves each reply; `ReplayBackend` answers from the file
and never opens a connection. Recording calls Foundry and costs money: it needs the household's yes
(Pim) first. Nothing secret is saved: requests are kept by digest only, replies are model text.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from kako.agents.chat import ChatReply, ChatRequest, reply_from_json, reply_to_json

FORMAT: Final = 1


class RecordingError(Exception):
    """A recording that is missing, malformed, or doesn't hold the call asked for."""


class ChatBackend(Protocol):
    """Sends one request to one deployment. `key` names the call for recordings; a live backend
    ignores it. Raises `ModelError` (kako.agents.model_manager) when the call fails."""

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply: ...

    @property
    def replays(self) -> bool:
        """True when replies come from a recording, not a model (`llm_call.recorded_replay`)."""
        ...


@dataclass(frozen=True)
class RecordedCall:
    key: str
    request_sha256: str
    reply: ChatReply


def read_recording(path: Path) -> dict[str, RecordedCall]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RecordingError(f"no recording at {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecordingError(f"{path} isn't JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise RecordingError(f"{path} isn't a recording in format {FORMAT}")
    calls: dict[str, RecordedCall] = {}
    for item in raw.get("calls", []):
        try:
            call = RecordedCall(
                str(item["key"]), str(item["request_sha256"]), reply_from_json(item["reply"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordingError(f"{path}: a malformed call ({exc})") from exc
        if call.key in calls:
            raise RecordingError(f"{path}: the key {call.key!r} is recorded twice")
        calls[call.key] = call
    return calls


def write_recording(path: Path, calls: dict[str, RecordedCall]) -> None:
    """Write the whole file, keys in order, then move it into place: never half a file."""
    body: dict[str, Any] = {
        "format": FORMAT,
        "calls": [
            {"key": c.key, "request_sha256": c.request_sha256, "reply": reply_to_json(c.reply)}
            for c in sorted(calls.values(), key=lambda c: c.key)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class ReplayBackend:
    """Answers each call from a recording. No network, no Azure settings."""

    def __init__(self, path: Path, *, strict: bool = True) -> None:
        self._calls = read_recording(path)
        self._path = path
        self._strict = strict
        self.drifted: list[str] = []  # keys whose request changed (lenient replay only)

    @property
    def replays(self) -> bool:
        return True

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        del deployment  # the recorded reply names the deployment that gave it
        call = self._calls.get(key)
        if call is None:
            raise RecordingError(f"{self._path} has no recorded call {key!r}: record it first")
        if call.request_sha256 != request.digest():
            if self._strict:
                raise RecordingError(
                    f"the request for {key!r} has changed since it was recorded in "
                    f"{self._path}: record it again (or replay with KAKO_REPLAY_STRICT=false)"
                )
            self.drifted.append(key)
        return call.reply


class RecordingBackend:
    """Calls the live backend and saves every reply under its key, after each call."""

    def __init__(self, live: ChatBackend, path: Path) -> None:
        if live.replays:
            raise RecordingError("record from a live backend, not a replay")
        self._live = live
        self._path = path
        self._calls = read_recording(path) if path.exists() else {}

    @property
    def replays(self) -> bool:
        return False

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        reply = await self._live.chat(request, deployment=deployment, key=key)
        self._calls[key] = RecordedCall(key, request.digest(), reply)
        write_recording(self._path, self._calls)
        return reply
