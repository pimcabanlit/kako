"""What the agents hand back, checked in code: allocations, citations, proposals and options.

Every amount an agent proposes is an **amount spec**, never a number it worked out:

- `none`: ₱0 a month;
- `rest`: the rest of the surplus after every other allocation (code does the subtraction);
- `figure:<ref>`: a figure's value, such as `figure:cashflow.monthly_surplus`;
- `fact:<ref>`: a fact's value, such as the current `fact:debt:credit-card/plan.allocation`;
- `said:<amount>`: an amount the household said in this turn's message, such as `said:4000`
  (code checks it is in the message).

Every citation names where a statement stands: `figure:<ref>` (the turn's run) or
`figure:<what-if>:<ref>`, `fact:<ref>`, `memory:<ref>`, `doc:<ref>`, `decision:<ref>`, or `said`
(the household's message). A proposal and an option each need at least one figure and one other
source (V-11).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from kako.engine.figures import Figure
from kako.planning.reconcile import Conflict

SourceKind = Literal["figure", "fact", "decision", "memory", "knowledge", "conversation"]
Specialist = Literal["budget", "debt", "savings", "goals"]
SPECIALISTS: tuple[Specialist, ...] = ("budget", "debt", "savings", "goals")


@dataclass(frozen=True)
class Allocation:
    entity_id: uuid.UUID
    entity_ref: str
    centavos: int  # a month
    spec: str  # how the agent named it: rest, figure:…, said:…


@dataclass(frozen=True)
class Citation:
    """One source, resolved: the kind and id `recommendation_source` stores, and what it says."""

    kind: SourceKind
    ref: str  # as the agent wrote it
    source_id: str  # a Kako id, a Meko memory or document id, or the turn seed
    shown: str  # the value or the quote, as the agent saw it
    figure: Figure | None = None  # for a figure: the figure itself
    what_if: str | None = None  # for a what-if's figure: its ref


@dataclass(frozen=True)
class SpecialistProposal:
    specialist: Specialist
    summary: str  # the specialist's recommendation, to be checked by the number check (task 5)
    allocations: tuple[Allocation, ...]
    what_if: str | None  # the what-if whose figures show the move
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Option:
    label: str  # "A: all extra on the card"
    summary: str
    what_if: str
    allocations: tuple[Allocation, ...]  # the what-if's allocations
    citations: tuple[Citation, ...]
    specialists: tuple[Specialist, ...]


@dataclass(frozen=True)
class Split:
    """A split the orchestrator tried while a conflict was open, and what the rules found in it."""

    what_if: str
    fits: bool
    conflicts: tuple[Conflict, ...]


@dataclass(frozen=True)
class Resolution:
    """How a turn's conflicts ended (`reconciliation`): found in code, resolved by the
    orchestrator with a split that fits and the option it rejected, or left to the household."""

    conflicts: tuple[Conflict, ...]
    described: tuple[str, ...]  # each conflict in words, with its figures
    together: str  # the what-if of the asks together
    together_allocations: tuple[Allocation, ...]
    splits: tuple[Split, ...]  # in the order tried, at most 3
    chosen: str | None  # the what-if of the option that resolves it; None: left to the household
    rejected: str | None  # the what-if it did not take
    rejected_allocations: tuple[Allocation, ...]
    reason: str  # checked by the number check like any other text (task 5)

    @property
    def attempts(self) -> int:
        return len(self.splits)


@dataclass(frozen=True)
class TurnAnswer:
    reply: str
    options: tuple[Option, ...]
    recommended: str | None  # an option's label, or None when the choice is the household's
    proposals: tuple[SpecialistProposal, ...]  # every specialist's answer, in the order asked
    resolution: Resolution | None = None  # None when the rules found no conflict
