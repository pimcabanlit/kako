"""The number check (rule V-10, docs/architecture.md step 7): every number in a text the agents
write must be one the engine produced, a fact Kako holds, or one the household said.

Code reads each number out of the text: peso amounts (₱9,050.00, 9,050 pesos), months
("9 months", "3-month target"), years ("2 years": 24 months, or 2), percentages (5.1%), dates
(Feb 15, 2028; March 3rd, 2028; 15 Feb 2028; 2028-02-15; 15/02/2028; Feb 15; Feb 2028), years and
any other number written in digits, and a spelled-out number with a unit ("nine months",
"twenty-four percent"). Each must match, at the precision it is written, one of:

- a figure of the turn's run, or of one of the turn's what-ifs (the asks together included);
- a fact in the turn's snapshot (money, a rate as a percentage, a whole number, a date);
- an allocation in one of the turn's what-ifs (a hypothetical fact, `scenario_override`);
- a number in the household's own message (an amount only from ₱100, as the tools take them), or
  the household's date.

A negative figure matches its amount ("₱5,050.00 more than the surplus" for -₱5,050.00).
Written at a lower precision a value is rounded half up to it ("2.1 months", "₱12,460").
Never a match: a number run into letters (`W1`), a number with a multiplier (`150k`, `₱2M`,
"12 thousand"), or one written with more than 6 decimals. Agents write numbers as the tools show
them. A specialist's summary, which the orchestrator reads, may name the turn's own refs exactly
(`debt1-W1`, `figure:debt1-W1:<ref>`, `fact:<ref>`); the reply, the options and the reason may not.
Other spelled-out numbers ("two options") aren't checked.

The texts: the reply, each option's label and summary, the resolution's reason and each
specialist's summary. A text that fails is sent back once with the numbers named
(`regenerated`); if it fails again it is shown with those numbers flagged (`fail`), never silently.
Every check is a `number_check` row.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from kako.agents.checks import Number, Subject, TextCheck
from kako.agents.tools import MESSAGE_CHARS, TurnState, said_amounts
from kako.engine.figures import Figure
from kako.facts.attributes import attribute
from kako.facts.model import FactRow, FactValue
from kako.facts.proposals import parse_fact, parse_life_event
from kako.facts.reading import MAX_DIGITS, MAX_PLACES, Kind, Token, scan

SHOWN_UNMATCHED: Final = 12  # the most unmatched numbers named back to the model


# --- What a number may be ------------------------------------------------------------------------


@dataclass
class Pool:
    """Every value a number may match, by kind, with what it is (the first source wins)."""

    money: dict[Decimal, str] = field(default_factory=dict)  # pesos, not negative
    months: dict[Decimal, str] = field(default_factory=dict)
    percent: dict[Decimal, str] = field(default_factory=dict)
    counts: dict[Decimal, str] = field(default_factory=dict)
    dates: dict[date, str] = field(default_factory=dict)
    refs: set[str] = field(default_factory=set)  # the turn's refs, for a specialist's summary

    def add_figure(self, figure: Figure, ref: str) -> None:
        self.refs.add(ref)
        value = figure.value
        if value is None:
            return
        if isinstance(value, date):
            self.dates.setdefault(value, ref)
        elif figure.unit == "centavos":
            self.money.setdefault(abs(Decimal(value)) / 100, ref)
        elif figure.unit == "months":
            self.months.setdefault(Decimal(value), ref)
        elif figure.unit == "ratio":
            if figure.key.endswith("_months"):
                self.months.setdefault(Decimal(value), ref)
            else:
                self.percent.setdefault(abs(Decimal(value)) * 100, ref)
        else:
            self.counts.setdefault(Decimal(value), ref)

    def add_number(self, kind: Kind, value: Decimal | date, ref: str) -> None:
        if isinstance(value, date):
            self.dates.setdefault(value, ref)
            return
        target = {
            "money": self.money,
            "months": self.months,
            "percent": self.percent,
        }.get(kind, self.counts)
        target.setdefault(abs(value), ref)


def _add_fact(pool: Pool, fact: FactRow, name: str) -> None:
    pool.refs.add(name)
    if fact.value_money is not None:
        pool.money.setdefault(Decimal(fact.value_money) / 100, name)
    if fact.value_rate is not None:
        pool.percent.setdefault(fact.value_rate * 100, name)
    if fact.value_int is not None:
        pool.counts.setdefault(Decimal(fact.value_int), name)
        pool.months.setdefault(Decimal(fact.value_int), name)
    if fact.value_date is not None:
        pool.dates.setdefault(fact.value_date, name)
    pool.dates.setdefault(fact.valid_from, name)  # "from Dec 1, 2026": when it took effect


def _held(state: TurnState) -> list[tuple[str, str | None, FactValue | None, date]]:
    """The changes this turn proposed (pending), each named by its change: a life event's day, and
    each fact's attribute, value and the day it takes effect."""
    found: list[tuple[str, str | None, FactValue | None, date]] = []
    for change in state.proposed:
        name = f"proposed:{change.ref}"
        for held in change.proposals:
            if held.kind == "life_event":
                found.append((name, None, None, parse_life_event(held.payload).occurs_on))
            else:
                fact = parse_fact(held.kind, held.payload)
                found.append((name, fact.attribute, fact.value, fact.valid_from))
    return found


def _add_held(pool: Pool, name: str, key: str | None, value: FactValue | None, on: date) -> None:
    pool.refs.add(name)
    pool.dates.setdefault(on, name)
    kind = attribute(key).value_type if key is not None else None
    if kind == "money" and isinstance(value, int):
        pool.money.setdefault(Decimal(value) / 100, name)
    elif kind == "rate" and isinstance(value, Decimal):
        pool.percent.setdefault(value * 100, name)
    elif kind == "int" and isinstance(value, int):
        pool.counts.setdefault(Decimal(value), name)
    elif kind == "date" and isinstance(value, date):
        pool.dates.setdefault(value, name)


def pool_of(state: TurnState) -> Pool:
    """Everything a number in this turn may match: the turn's run first, then each what-if in the
    order it ran, the snapshot's facts, the what-ifs' allocations, the household's own words."""
    pool = Pool()
    refs = state.refs
    for figure in state.run.figures:
        pool.add_figure(figure, f"figure:{refs.figure(figure)}")
    for ref, what_if in state.what_ifs.items():
        for figure in what_if.run.figures:
            pool.add_figure(figure, f"figure:{ref}:{refs.figure(figure)}")
    for fact in state.snapshot.facts:
        _add_fact(pool, fact, f"fact:{refs.fact(fact)}")
    replan = state.inputs.replan
    if replan is not None:  # what changed: the figures and facts the household last decided on
        for figure in replan.before.figures:
            pool.add_figure(figure, f"before:figure:{refs.figure(figure)}")
        for change in (*replan.diff.fact_changes, *(f for r in replan.revisit for f in r.facts)):
            for row in (change.old, change.new):
                if row is not None:
                    _add_fact(pool, row, f"before:fact:{refs.fact(row)}")
    for ref, what_if in state.what_ifs.items():
        for a in what_if.allocations:
            pool.money.setdefault(Decimal(a.centavos) / 100, f"allocation:{ref}:{a.entity_ref}")
    for name, key, value, on in _held(state):  # what this turn proposed, from their words
        _add_held(pool, name, key, value, on)
    said = said_amounts(state.message[:MESSAGE_CHARS])
    for token in scan(state.message[:MESSAGE_CHARS]):
        for day in token.dates:
            pool.dates.setdefault(day, "said")
        if token.kind == "month" and token.year_month is not None:
            pool.dates.setdefault(date(*token.year_month, 1), "said")
        if token.value is None or token.places > MAX_PLACES:
            continue
        if token.kind == "number":
            # A bare number is a count ("2 kids"), and an amount only from ₱100, as the tools
            # take amounts from the household's words ("4000 extra").
            pool.counts.setdefault(token.value, "said")
            if int(token.value * 100) in said:
                pool.money.setdefault(token.value, "said")
        elif token.pools == ("years",):
            pool.months.setdefault(token.value * 12, "said")
        else:
            target = {"money": pool.money, "months": pool.months, "percent": pool.percent}
            target[token.kind].setdefault(token.value, "said")
    pool.dates.setdefault(state.snapshot.on, "date:today")
    pool.refs |= set(state.what_ifs)
    return pool


# --- Matching ----------------------------------------------------------------------------------


def _round(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _find(candidates: dict[Decimal, str], value: Decimal, places: int) -> str | None:
    exact = candidates.get(value)
    if exact is not None:
        return exact
    return next((ref for c, ref in candidates.items() if _round(c, places) == value), None)


def _match(token: Token, pool: Pool) -> str | None:
    if token.kind in ("code", "scaled"):
        return None
    if token.dates:
        return next((pool.dates[d] for d in token.dates if d in pool.dates), None)
    if token.day_of is not None:
        month, day = token.day_of
        return next((r for d, r in pool.dates.items() if (d.month, d.day) == (month, day)), None)
    if token.kind in ("date",):
        return None  # a date that is no real day
    if token.year_month is not None and token.kind == "month":
        year, month = token.year_month
        return next((r for d, r in pool.dates.items() if (d.year, d.month) == (year, month)), None)
    value, places = token.value, token.places
    if value is None or places > MAX_PLACES or len(value.as_tuple().digits) > MAX_DIGITS:
        return None
    for name in token.pools:
        if name == "years":
            found = _find(pool.months, value * 12, places) or _find(pool.counts, value, places)
        else:
            found = _find(getattr(pool, name), value, places)
        if found is not None:
            return found
    if token.year_month is not None:  # a bare year
        return next((r for d, r in pool.dates.items() if d.year == token.year_month[0]), None)
    return None


def check_text(
    subject: Subject,
    label: str,
    text: str,
    pool: Pool,
    names: Iterable[str] = (),
    *,
    refs_allowed: bool = False,
) -> TextCheck:
    """Every number in `text`, each with what it matched. With `refs_allowed` (a specialist's
    summary, which only the orchestrator reads) a ref of this turn is a ref, not a number."""
    numbers = []
    for token in scan(text, names):
        match = _match(token, pool)
        if token.kind == "code" and refs_allowed and token.text in pool.refs:
            match = "ref"
        numbers.append(Number(token.text, token.kind, match))
    return TextCheck(subject, label, text, tuple(numbers))


def names_of(state: TurnState) -> tuple[str, ...]:
    """The household's own names (people and things), left out of the check."""
    return (*(name for name, _ in state.inputs.people), *(e.name for e in state.entities))


def check_texts(
    state: TurnState, texts: Sequence[tuple[Subject, str, str]], *, refs_allowed: bool = False
) -> tuple[TextCheck, ...]:
    pool = pool_of(state)
    names = names_of(state)
    return tuple(
        check_text(s, label, text, pool, names, refs_allowed=refs_allowed)
        for s, label, text in texts
    )


def mismatch(checks: Sequence[TextCheck]) -> str:
    """What the model is told when a text fails: each number that matched nothing, and where."""

    def listed(refs: bool) -> str:
        named = list(
            dict.fromkeys(
                f"{n.text!r} in {c.label}"
                for c in checks
                for n in c.unmatched
                if (n.kind == "code") == refs
            )
        )
        more = len(named) - SHOWN_UNMATCHED
        return "; ".join(named[:SHOWN_UNMATCHED]) + (f"; and {more} more" if more > 0 else "")

    parts = []
    numbers = listed(refs=False)
    if numbers:
        parts.append(
            f"the number check found numbers that match no figure, fact or what-if of this turn: "
            f"{numbers}. Write only figures exactly as a tool or the brief shows them (such as "
            "₱9,050.00 or 9 months), or leave the number out; never work one out"
        )
    refs = listed(refs=True)
    if refs:
        parts.append(
            f"the text has refs or codes in it: {refs}. The reader sees plain words: take each "
            "one out and say what it shows, keeping the figures themselves as the tools show them"
        )
    return ". Also, ".join(parts)
