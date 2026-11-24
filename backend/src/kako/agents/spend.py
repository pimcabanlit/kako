"""What model calls cost, and where each one is written down (`llm_call`).

`cost_usd` prices one call from the per-token prices in settings at the time of the call. The log
is `DbLlmLog` (`kako.db.llm_log`) in Postgres, or `MemoryLlmLog` here for tests. Every call is
logged, made or refused, so the metrics page and the daily cap read the same rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

from kako.agents.chat import CallAgent

Outcome = Literal["ok", "error", "budget_exceeded"]
MILLION = Decimal(1_000_000)
MICRO_DOLLAR = Decimal("0.000001")  # llm_call.cost_usd is NUMERIC(12,6)


def cost_usd(
    prices: tuple[Decimal, Decimal, Decimal],
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
) -> Decimal:
    """US$ for one call: uncached input, cached input and output at their prices per million
    tokens, rounded half up to a millionth of a dollar once, at the end."""
    price_in, price_cached, price_out = prices
    cached = min(cached_tokens, input_tokens)
    total = (input_tokens - cached) * price_in + cached * price_cached + output_tokens * price_out
    return (total / MILLION).quantize(MICRO_DOLLAR, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LlmCallRecord:
    """One row of `llm_call`."""

    session_id: uuid.UUID | None
    meko_turn_seed: str | None
    agent: CallAgent
    deployment: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    latency_ms: int
    cost_usd: Decimal
    outcome: Outcome
    recorded_replay: bool
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class LlmLog(Protocol):
    async def write(self, record: LlmCallRecord) -> None:
        """Keep one call, made or refused. Commits on its own, so a call that cost money is
        counted even when the turn around it fails."""
        ...

    async def spent_since(self, since: datetime) -> Decimal:
        """US$ of real calls (not replays) logged at or after `since`."""
        ...


class MemoryLlmLog:
    """The log in memory, for unit tests."""

    def __init__(self) -> None:
        self.records: list[LlmCallRecord] = []

    async def write(self, record: LlmCallRecord) -> None:
        self.records.append(record)

    async def spent_since(self, since: datetime) -> Decimal:
        return sum(
            (r.cost_usd for r in self.records if not r.recorded_replay and r.created_at >= since),
            Decimal(0),
        )
