"""Per-turn figures and their average and worst case, from a turn's `llm_call` rows. Pure.

A turn's seconds are its model time as the turn ran it: the orchestrator's calls one after another,
and between two of them the specialists it asked side by side, so the slowest specialist's calls
count and the others' don't. The rows are in the order they were logged, each after its call came
back, so the specialists of one round come between the orchestrator call that asked them and the
next. A replayed call keeps the latency and cost of the call it replays, so a replayed turn's
figures are its recording's on Foundry. Meko's and the database's time is not counted.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

ORCHESTRATOR: Final = "orchestrator"
CENT_FRACTION: Final = Decimal("0.000001")  # costs are kept to a millionth of a dollar


@dataclass(frozen=True)
class Call:
    """One `llm_call` row, as the metrics read it."""

    agent: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: Decimal
    replayed: bool


def model_ms(calls: Sequence[Call]) -> int:
    """The turn's model time: orchestrator calls in a row, each round of specialists as long as its
    slowest specialist's calls added up."""
    total = 0
    side: dict[str, int] = {}
    for call in calls:
        if call.agent == ORCHESTRATOR:
            total += max(side.values(), default=0) + call.latency_ms
            side.clear()
        else:
            side[call.agent] = side.get(call.agent, 0) + call.latency_ms
    return total + max(side.values(), default=0)


@dataclass(frozen=True)
class TurnFigures:
    session_id: uuid.UUID
    seed: str
    title: str
    model_calls: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: Decimal
    model_ms: int
    replayed: bool  # every call replayed from a recording
    brief_tokens: int | None  # the brief's size, when the turn kept it

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def turn_figures(
    session_id: uuid.UUID,
    seed: str,
    title: str,
    calls: Sequence[Call],
    brief_tokens: int | None = None,
) -> TurnFigures:
    """One turn's figures from its calls, in the order they were logged."""
    return TurnFigures(
        session_id=session_id,
        seed=seed,
        title=title,
        model_calls=len(calls),
        input_tokens=sum(c.input_tokens for c in calls),
        output_tokens=sum(c.output_tokens for c in calls),
        cached_tokens=sum(c.cached_tokens for c in calls),
        cost_usd=sum((c.cost_usd for c in calls), Decimal(0)),
        model_ms=model_ms(calls),
        replayed=bool(calls) and all(c.replayed for c in calls),
        brief_tokens=brief_tokens,
    )


@dataclass(frozen=True)
class Spread:
    """A measure's average over the turns, its worst case and the turn it came from."""

    average: Decimal
    worst: Decimal
    worst_session_id: uuid.UUID
    worst_seed: str
    worst_title: str


def spread(
    turns: Sequence[TurnFigures], measure: Callable[[TurnFigures], Decimal | int | None]
) -> Spread | None:
    """The average (not rounded) and the worst (the highest; the first such turn) of `measure`
    over the turns that have it; None when none do."""
    measured = [(t, Decimal(v)) for t in turns if (v := measure(t)) is not None]
    if not measured:
        return None
    worst_turn, worst = measured[0]
    for turn, value in measured[1:]:
        if value > worst:
            worst_turn, worst = turn, value
    average = sum((v for _, v in measured), Decimal(0)) / len(measured)
    return Spread(average, worst, worst_turn.session_id, worst_turn.seed, worst_turn.title)


def whole(value: Decimal) -> int:
    """Half up to a whole number (tokens, calls, milliseconds)."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def dollars(value: Decimal) -> Decimal:
    """Half up to a millionth of a dollar, as `llm_call` keeps costs."""
    return value.quantize(CENT_FRACTION, rounding=ROUND_HALF_UP)


def seconds(ms: Decimal) -> Decimal:
    """Milliseconds as seconds to one decimal, half up."""
    return (ms / 1000).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def share(part: int, total: int) -> Decimal | None:
    """`part` of `total` as a percentage to one decimal, half up; None when there is no total."""
    if total <= 0:
        return None
    return (Decimal(part) * 100 / total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
