"""One planning turn's running totals: its token budget, and the agents' steps in order.

Every model call and tool call in a turn shares one `TurnContext`. The model manager charges each
call's tokens to it and refuses a call that would go over the turn's budget; the tool loop numbers
each tool call (`agent_step.seq`) and writes it to the step log. `DbStepLog`
(`kako.db.agent_steps`) is the Postgres log; `MemoryStepLog` here is for tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from kako.agents.prompt_registry import PromptVersion

StepAgent = Literal["orchestrator", "budget", "debt", "savings", "goals", "dreaming"]
StepOutcome = Literal["ok", "rejected", "error"]
SUMMARY_CHARS = 240  # agent_step summaries are for display, never a full prompt


def short(text: str, limit: int = SUMMARY_CHARS) -> str:
    """One line, at most `limit` characters."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


@dataclass(frozen=True)
class StepRecord:
    """One row of `agent_step`: one tool call by one agent."""

    session_id: uuid.UUID | None
    meko_turn_seed: str
    agent: StepAgent
    seq: int
    tool: str
    input_summary: str
    result_summary: str
    calc_run_id: uuid.UUID | None
    outcome: StepOutcome
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class StepLog(Protocol):
    async def write(self, step: StepRecord) -> None: ...


class MemoryStepLog:
    def __init__(self) -> None:
        self.steps: list[StepRecord] = []

    async def write(self, step: StepRecord) -> None:
        self.steps.append(step)


@dataclass
class TurnContext:
    """A planning turn: the session (None outside one), the Meko turn seed, and its budget."""

    meko_turn_seed: str
    token_budget: int
    steps: StepLog = field(default_factory=MemoryStepLog)
    session_id: uuid.UUID | None = None
    tokens_used: int = 0
    tokens_reserved: int = 0  # worst cases of calls in flight: parallel calls can't overspend
    # The steps that ran each what-if, by its ref: they name its run once the turn is kept.
    what_if_steps: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    # The prompts the turn's agents ran with, by name: the turn names them in its Meko trace.
    prompts: dict[str, PromptVersion] = field(default_factory=dict)
    _seq: int = 0

    def next_seq(self) -> int:
        """The next step number in this turn, from 1."""
        self._seq += 1
        return self._seq

    def tokens_left(self) -> int:
        return max(self.token_budget - self.tokens_used - self.tokens_reserved, 0)
