"""V-09: every number in a proposal appears in its quoted evidence.

Dreaming and the agents copy what the household said; they never work a number out
(docs/data-model.md, `proposal_evidence`; REVIEW.md rule 2). So before a proposal is stored, code
reads each number it would write (a money value, a rate, a whole number, a date, and any number in
its free text) and looks for it among the numbers in its quotes, read the way the number check
reads text (`facts.reading`).

What counts as the same number:

- **Money:** the same amount in pesos (₱68,000, 68,000 pesos, 68000, and in the household's words
  also 68k or 68 thousand).
- **A rate:** the same percentage (3.5%), or the same decimal (0.035).
- **A whole number:** the same number, in digits or as a count of months or years.
- **A date:** the same day in any common form; a day with no year (Dec 1) when it falls within a
  year of the household's date; a month with its year (December 2026) for the first of that month.
  A start date may also be the household's own date (`today`): a statement of how things are now
  takes effect the day it is said.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from kako.facts.attributes import attribute
from kako.facts.proposals import FACT_KINDS, PayloadError, parse_fact, parse_life_event
from kako.facts.reading import MAX_PLACES, scan

YEAR_DAYS: Final = 366
_SCALES: Final = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
}
_SCALED: Final = re.compile(
    r"(?:₱|PHP\s?|P)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<scale>[a-z]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Wanted:
    """One number a proposal would write: what it is, and its value."""

    what: str  # for the error: "the value", "valid_from", "a number in the description"
    kind: str  # money (pesos), rate (a fraction), number, date, day (month, day), month
    value: Decimal | date | tuple[int, int]
    today_ok: bool = False  # a start date may be the household's own date


@dataclass
class QuotePool:
    """Every number in the quotes."""

    numbers: set[Decimal] = field(default_factory=set)  # plain values, money in pesos
    percents: set[Decimal] = field(default_factory=set)
    dates: set[date] = field(default_factory=set)
    days: set[tuple[int, int]] = field(default_factory=set)  # (month, day) with no year
    months: set[tuple[int, int]] = field(default_factory=set)  # (year, month)


def quote_pool(quotes: Iterable[str]) -> QuotePool:
    pool = QuotePool()
    for quote in quotes:
        for token in scan(quote):
            pool.dates.update(token.dates)
            if token.day_of is not None:
                pool.days.add(token.day_of)
            if token.kind == "month" and token.year_month is not None:
                pool.months.add(token.year_month)
            if token.kind == "scaled":
                scaled = _scaled(token.text)
                if scaled is not None:
                    pool.numbers.add(scaled)
                continue
            if token.value is None or token.places > MAX_PLACES:
                continue
            if token.kind == "percent":
                pool.percents.add(token.value)
            elif token.pools == ("years",):
                pool.numbers.update({token.value, token.value * 12})
            else:
                pool.numbers.add(token.value)
    return pool


def _scaled(text: str) -> Decimal | None:
    """68k, ₱1.2M, 68 thousand: in the household's words, the amount it says."""
    match = _SCALED.fullmatch(text.strip())
    if match is None:
        return None
    factor = _SCALES.get(match["scale"].lower())
    if factor is None:
        return None
    try:
        return Decimal(match["num"].replace(",", "")) * factor
    except InvalidOperation:
        return None


def _found(wanted: Wanted, pool: QuotePool, today: date | None) -> bool:
    if isinstance(wanted.value, tuple):
        if wanted.kind == "day":  # a day with no year: said so, or a full date on that day
            month, day_of = wanted.value
            return wanted.value in pool.days or any(
                (d.month, d.day) == (month, day_of) for d in pool.dates
            )
        return wanted.value in pool.months or any(
            (d.year, d.month) == wanted.value for d in pool.dates
        )
    if isinstance(wanted.value, date):
        day = wanted.value
        if wanted.today_ok and day == today:
            return True
        if day in pool.dates or ((day.year, day.month) in pool.months and day.day == 1):
            return True
        near = today is None or abs((day - today).days) <= YEAR_DAYS
        return near and (day.month, day.day) in pool.days
    if wanted.kind == "rate":
        return wanted.value * 100 in pool.percents or wanted.value in pool.numbers
    return wanted.value in pool.numbers


def _text_numbers(what: str, text: str) -> list[Wanted]:
    """The numbers in a free text the proposal writes (a description, a note, a reason)."""
    wanted: list[Wanted] = []
    for token in scan(text):
        for day in token.dates:
            wanted.append(Wanted(what, "date", day))
        if token.day_of is not None:
            wanted.append(Wanted(what, "day", token.day_of))
        if token.kind == "month" and token.year_month is not None:
            wanted.append(Wanted(what, "month", token.year_month))
        if token.kind in ("date", "month"):
            continue
        if token.kind == "scaled":
            scaled = _scaled(token.text)
            if scaled is not None:
                wanted.append(Wanted(what, "number", scaled))
        elif token.kind == "code" or token.value is None:
            continue
        elif token.kind == "percent":
            wanted.append(Wanted(what, "rate", token.value / 100))
        else:
            wanted.append(Wanted(what, "number", token.value))
    return wanted


def payload_numbers(kind: str, payload: Mapping[str, Any]) -> list[Wanted]:
    """Every number a proposal of `kind` would write. Ids are not numbers."""
    if kind in FACT_KINDS:
        write = parse_fact(kind, payload)
        attr = attribute(write.attribute)
        wanted: list[Wanted] = []
        value = write.value
        if attr.value_type == "money":
            wanted.append(Wanted("the value", "money", Decimal(int(value)) / 100))  # type: ignore[arg-type]
        elif attr.value_type == "rate":
            wanted.append(Wanted("the value", "rate", value))  # type: ignore[arg-type]
        elif attr.value_type == "int":
            wanted.append(Wanted("the value", "number", Decimal(int(value))))  # type: ignore[arg-type]
        elif attr.value_type == "date":
            wanted.append(Wanted("the value", "date", value))  # type: ignore[arg-type]
        else:
            wanted += _text_numbers("a number in the value", str(value))
        wanted.append(Wanted("valid_from", "date", write.valid_from, today_ok=True))
        if write.valid_to is not None:
            wanted.append(Wanted("valid_to", "date", write.valid_to))
        return wanted
    if kind == "retract_fact":
        return _text_numbers("a number in the reason", str(payload.get("reason", "")))
    if kind == "life_event":
        event = parse_life_event(payload)
        return [
            Wanted("occurs_on", "date", event.occurs_on, today_ok=True),
            *_text_numbers("a number in the description", event.description),
        ]
    if kind == "decision":
        # The options and their figures come from a stored plan, whose texts passed the number
        # check (V-10); the household's own reasoning is checked here.
        valid_from = payload.get("valid_from")
        found = _text_numbers("a number in the reasoning", str(payload.get("reasoning", "")))
        if isinstance(valid_from, str):
            try:
                found.append(Wanted("valid_from", "date", date.fromisoformat(valid_from), True))
            except ValueError as exc:
                raise PayloadError(f"valid_from: {valid_from!r} isn't a date") from exc
        return found
    return []  # promote: ids only


def _shown(wanted: Wanted) -> str:
    if isinstance(wanted.value, tuple):
        first, second = wanted.value
        if wanted.kind == "day":
            return date(2000, first, second).strftime("%b %-d")
        return date(first, second, 1).strftime("%b %Y")
    if isinstance(wanted.value, date):
        return wanted.value.isoformat()
    if wanted.kind == "money":
        return f"₱{wanted.value:,.2f}"
    if wanted.kind == "rate":
        return f"{(wanted.value * 100).normalize():f}%"
    return f"{wanted.value.normalize():f}"


def unquoted(
    kind: str, payload: Mapping[str, Any], quotes: Sequence[str], *, today: date | None
) -> list[str]:
    """V-09: each number the proposal would write that its quotes don't hold, described; empty
    when every number is quoted. `today` is the household's date when it was said."""
    pool = quote_pool(quotes)
    return [
        f"{w.what} {_shown(w)}"
        for w in payload_numbers(kind, payload)
        if not _found(w, pool, today)
    ]
