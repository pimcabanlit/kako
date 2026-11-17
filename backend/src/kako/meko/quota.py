"""The call counter and the quota guard: every Meko call is counted, and refused past its ceiling.

Meko Cloud's Free tier caps some tools for the account's lifetime (docs/architecture.md, Cost plan),
and using them up loses the demo (REVIEW.md rule 9). So before a call is sent, the guard reserves it
in the call log; on Meko Cloud a capped tool past this environment's ceiling is refused, logged as
`refused`, and never sent. After the call, its row gets its outcome, latency and result count.

A reserved call counts even if it then fails or the process stops: the allowance may already be
spent. The count is this environment's (one database), not the account's: calls made elsewhere,
such as the Phase 1 spikes, aren't in it.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal, Protocol

from kako.meko.client import MekoError

Target = Literal["local", "cloud"]
Outcome = Literal["ok", "error", "refused"]

# Each capped tool and the allowance its calls count against. `selflearning_verify` replays a
# search, and Meko counts it as one (docs/meko-setup.md).
COUNTED_AS: Final[dict[str, str]] = {
    "context_search": "context_search",
    "selflearning_verify": "context_search",
    "memory_search": "memory_search",
    "knowledgebase_search": "knowledgebase_search",
    "conversation_add_message": "conversation_add_message",
    "conversation_create": "conversation_create",
    "memory_add": "memory_add",
}
# The Free tier's lifetime allowance for each (account-wide; Meko's tool reference, Nov 2026).
FREE_ALLOWANCE: Final[dict[str, int]] = {
    "context_search": 1_000,
    "memory_search": 1_000,
    "knowledgebase_search": 1_000,
    "conversation_add_message": 1_000,
    "conversation_create": 1_000,
    "memory_add": 10_000,
}


class MekoQuotaError(MekoError):
    """The call would pass this environment's ceiling for a capped tool; it was not sent."""


def tools_counted_with(tool: str) -> tuple[str, ...]:
    """Every tool whose calls count against the same allowance as `tool` (itself included)."""
    allowance = COUNTED_AS.get(tool)
    if allowance is None:
        return (tool,)
    return tuple(sorted(t for t, a in COUNTED_AS.items() if a == allowance))


def ceiling_for(target: Target, tool: str, cloud_ceiling: int) -> int | None:
    """The most calls allowed for `tool`, or None for no ceiling (local Meko, or a tool the Free
    tier doesn't cap). Never above the Free tier's own allowance."""
    allowance = COUNTED_AS.get(tool)
    if target == "local" or allowance is None:
        return None
    return min(cloud_ceiling, FREE_ALLOWANCE[allowance])


class CallLog(Protocol):
    """Where calls are counted: `meko_call` in Postgres (`DbCallLog`), or memory for tests."""

    async def reserve(
        self, target: Target, tool: str, agent_id: str, ceiling: int | None
    ) -> uuid.UUID:
        """Count the call before it is sent, or log it `refused` and raise MekoQuotaError when
        `ceiling` calls counted with it were already made. Atomic: two callers can't both take
        the last call."""
        ...

    async def finish(
        self, call_id: uuid.UUID, outcome: Outcome, latency_ms: int, result_count: int | None
    ) -> None: ...

    async def used(self, target: Target) -> dict[str, int]:
        """Calls made (not refused) on `target`, by tool."""
        ...


@dataclass
class CallRecord:
    id: uuid.UUID
    target: Target
    tool: str
    agent_id: str
    outcome: Outcome
    latency_ms: int | None = None
    result_count: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MemoryCallLog:
    """The call log in memory, for unit tests and the fake."""

    def __init__(self) -> None:
        self.calls: list[CallRecord] = []

    async def reserve(
        self, target: Target, tool: str, agent_id: str, ceiling: int | None
    ) -> uuid.UUID:
        record = CallRecord(uuid.uuid4(), target, tool, agent_id, "ok")
        if ceiling is not None and self._count(target, tool) >= ceiling:
            record.outcome = "refused"
            self.calls.append(record)
            raise quota_refusal(tool, ceiling)
        self.calls.append(record)
        return record.id

    async def finish(
        self, call_id: uuid.UUID, outcome: Outcome, latency_ms: int, result_count: int | None
    ) -> None:
        record = next(r for r in self.calls if r.id == call_id)
        record.outcome, record.latency_ms, record.result_count = outcome, latency_ms, result_count

    async def used(self, target: Target) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.calls:
            if r.target == target and r.outcome != "refused":
                counts[r.tool] = counts.get(r.tool, 0) + 1
        return counts

    def _count(self, target: Target, tool: str) -> int:
        tools = tools_counted_with(tool)
        return sum(
            1
            for r in self.calls
            if r.target == target and r.tool in tools and r.outcome != "refused"
        )


def quota_refusal(tool: str, ceiling: int) -> MekoQuotaError:
    return MekoQuotaError(
        f"{tool} has reached this environment's ceiling of {ceiling} calls on Meko Cloud "
        "(KAKO_MEKO_CLOUD_CEILING); nothing was sent"
    )


@dataclass
class CallResult:
    """What the caller reports about a call while it is open: how many results came back."""

    result_count: int | None = None


class Quota:
    """The guard every adapter call goes through: reserve, call, record the outcome."""

    def __init__(self, log: CallLog, target: Target, cloud_ceiling: int) -> None:
        if cloud_ceiling < 0:
            raise ValueError("the ceiling can't be negative")
        self.log = log
        self.target: Target = target
        self.cloud_ceiling = cloud_ceiling

    @asynccontextmanager
    async def call(self, tool: str, agent_id: str) -> AsyncIterator[CallResult]:
        """```
        async with quota.call("context_search", "kako:orchestrator") as result:
            answer = await session.call_tool(...)
            result.result_count = len(answer)
        ```
        Raises MekoQuotaError before anything is sent when the ceiling is reached."""
        ceiling = ceiling_for(self.target, tool, self.cloud_ceiling)
        call_id = await self.log.reserve(self.target, tool, agent_id, ceiling)
        result = CallResult()
        started = time.monotonic()
        try:
            yield result
        except BaseException:
            await self.log.finish(call_id, "error", _since(started), None)
            raise
        await self.log.finish(call_id, "ok", _since(started), result.result_count)

    async def left(self) -> dict[str, int | None]:
        """For each capped allowance, the calls still allowed here (None: no ceiling)."""
        used = await self.log.used(self.target)
        left: dict[str, int | None] = {}
        for allowance in sorted(FREE_ALLOWANCE):
            ceiling = ceiling_for(self.target, allowance, self.cloud_ceiling)
            spent = sum(used.get(t, 0) for t in tools_counted_with(allowance))
            left[allowance] = None if ceiling is None else max(ceiling - spent, 0)
        return left


def _since(started: float) -> int:
    return max(round((time.monotonic() - started) * 1000), 0)
