"""Scoring a test-set answer in code: each expectation of a question is one check, passed or not.

Pure: it reads the checked answer (`TurnAnswer`) and what the turn's tools read (`TurnState`: the
snapshot for the current allocations, the refs for the figures). No model judges an answer: a
number is read out of the text the way the number check reads it (`facts.reading.scan`), so
"₱9,050", "₱9,050.00" and "9,050.00 pesos" all state ₱9,050.00, and "2.14 months" states 2.1 months.

What the household reads: the reply, each option's label and summary, the figures each option cites,
and the resolution's reason. A failed turn (no answer) scores 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from kako.agents.answers import Citation, Option, TurnAnswer
from kako.agents.tools import TurnState
from kako.evals.questions import Move, Question, centavos
from kako.facts.reading import Token, scan

ALLOCATION: Final = "plan.allocation"
# Kinds that state the same sort of value: a month count may be written in months, an amount with ₱.
SAME: Final[dict[str, frozenset[str]]] = {
    "money": frozenset({"money", "number"}),
    "months": frozenset({"months"}),
    "percent": frozenset({"percent"}),
    "number": frozenset({"number", "money", "months", "percent"}),
}


@dataclass(frozen=True)
class Check:
    name: str  # such as "states ₱9,050.00"
    passed: bool
    detail: str = ""  # why it failed, in a few words


@dataclass(frozen=True)
class Score:
    question: str
    checks: tuple[Check, ...]

    @property
    def passed(self) -> int:
        return sum(c.passed for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def value(self) -> float:
        """The share of checks passed; 0 when the turn gave no answer."""
        if not self.checks or not self.checks[0].passed:
            return 0.0
        return self.passed / self.total


def score(question: Question, answer: TurnAnswer | None, state: TurnState | None) -> Score:
    expect = question.expect
    if answer is None or state is None:
        return Score(question.id, (Check("answered", False, "the turn failed"),))
    checks = [Check("answered", True)]
    flagged = [n.text for c in answer.checks for n in c.unmatched]
    checks.append(Check("numbers", not flagged, ", ".join(flagged)))
    texts = _shown(answer)
    read = [t for text in texts for t in scan(text)]
    for wanted in expect.states:
        either = alternatives(wanted)
        name = " or ".join(either)
        checks.append(Check(f"states {name}", any(_states(w, read) for w in either)))
    reply = answer.reply.lower()
    for word in expect.words:
        checks.append(Check(f"says {word!r}", word.lower() in reply))
    if expect.options is not None:
        low, high = expect.options
        n = len(answer.options)
        checks.append(Check(f"{low} to {high} options", low <= n <= high, f"{n} options"))
    current = current_allocations(state)
    moves = {o.label: effective(o, current) for o in answer.options}
    for move in expect.allocations:
        found = next((label for label, m in moves.items() if _has(m, move)), None)
        checks.append(Check(f"offers {_move_text(move)}", found is not None))
    recommended = next((o for o in answer.options if o.label == answer.recommended), None)
    if expect.recommended == "none":
        checks.append(Check("leaves the choice", recommended is None, answer.recommended or ""))
    if expect.not_recommended is not None:
        bad = recommended is not None and _has(moves[recommended.label], expect.not_recommended)
        checks.append(Check(f"doesn't recommend {_move_text(expect.not_recommended)}", not bad))
    citations = [c for o in answer.options for c in o.citations]
    cited = {figure_ref(c, state) for c in citations if c.kind == "figure"}
    for ref in expect.cites:
        checks.append(Check(f"cites {ref}", ref in cited))
    for source in expect.sources:
        checks.append(Check(f"cites {source}", any(_is(source, c) for c in citations)))
    return Score(question.id, tuple(checks))


def _shown(answer: TurnAnswer) -> list[str]:
    texts = [answer.reply]
    for option in answer.options:
        texts += [option.label, option.summary]
        texts += [c.shown for c in option.citations if c.kind == "figure"]
    if answer.resolution is not None:
        texts.append(answer.resolution.reason)
    return texts


def alternatives(wanted: str) -> list[str]:
    """`15 months | Feb 16, 2028`: either states the figure (a payoff as a duration or a date)."""
    return [w.strip() for w in wanted.split("|")]


def _states(wanted: str, read: Iterable[Token]) -> bool:
    """Whether a number read out of the texts states `wanted`, written as the tools write it."""
    [target] = scan(wanted)
    for token in read:
        if target.dates:
            if set(target.dates) & set(token.dates):
                return True
            continue
        if target.value is None or token.value is None:
            continue
        value = token.value * 12 if token.pools == ("years",) else token.value
        kind = "months" if token.pools == ("years",) else token.kind
        if kind not in SAME[target.kind]:
            continue
        rounded = value.quantize(Decimal(1).scaleb(-target.places), rounding=ROUND_HALF_UP)
        if rounded == target.value:
            return True
    return False


def current_allocations(state: TurnState) -> dict[str, int]:
    """Each entity's monthly allocation in the turn's snapshot, by ref."""
    return {
        state.refs.by_id[f.entity_id]: f.value_money or 0
        for f in state.snapshot.facts
        if f.attribute == ALLOCATION and f.entity_id is not None
    }


def effective(option: Option, current: dict[str, int]) -> dict[str, int]:
    """An option's allocations as the household would have them: what it names, and the current
    allocation for everything else."""
    return {**current, **{a.entity_ref: a.centavos for a in option.allocations}}


def _has(allocations: dict[str, int], move: Move) -> bool:
    return all(allocations.get(ref, 0) == centavos(amount) for ref, amount in move.items())


def _move_text(move: Move) -> str:
    return ", ".join(f"{ref} {amount}" for ref, amount in sorted(move.items()))


def figure_ref(c: Citation, state: TurnState) -> str:
    """A cited figure as `key@entity`, whichever run it came from."""
    return state.refs.figure(c.figure) if c.figure is not None else ""


def _is(source: str, c: Citation) -> bool:
    if source == "said":
        return c.kind == "conversation"
    if source == "memory":
        return c.kind == "memory"
    if source == "doc":
        return c.kind == "knowledge"
    kind, _, ref = source.partition(":")
    return c.kind == kind and c.ref.strip() == source and bool(ref)
