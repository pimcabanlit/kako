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

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from kako.agents.checks import Kind, Number, Subject, TextCheck
from kako.agents.tools import MESSAGE_CHARS, TurnState, said_amounts
from kako.engine.figures import Figure

_MONTHS: Final = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MON = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"


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
        name = f"fact:{refs.fact(fact)}"
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
    for ref, what_if in state.what_ifs.items():
        for a in what_if.allocations:
            pool.money.setdefault(Decimal(a.centavos) / 100, f"allocation:{ref}:{a.entity_ref}")
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


# --- Reading numbers out of a text ------------------------------------------------------------

_UNITS: Final = [
    *("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"),
    *("eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen"),
    *("eighteen", "nineteen"),
]
_TENS: Final = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_WORDNUM = (
    rf"(?:{'|'.join(_TENS)})(?:[\s-](?:{'|'.join(_UNITS[1:10])}))?|{'|'.join(reversed(_UNITS))}"
)
_ORD = r"(?:st|nd|rd|th)?"
TOKEN: Final = re.compile(
    rf"(?P<iso>\b(?P<iy>\d{{4}})-(?P<im>\d{{1,2}})-(?P<id>\d{{1,2}})\b)"
    rf"|(?P<slash>\b(?P<s1>\d{{1,2}})/(?P<s2>\d{{1,2}})/(?P<s3>\d{{4}}|\d{{2}})\b)"
    rf"|(?P<date>\b(?P<dmon>{_MON})\.?\s+(?P<day>\d{{1,2}}){_ORD}\b(?:,?\s+(?P<dyear>\d{{4}})\b)?)"
    rf"|(?P<first>\b(?:the\s+)?(?P<fday>\d{{1,2}}){_ORD}\s+(?:of\s+)?(?P<fmon>{_MON})\b\.?"
    rf"(?:,?\s+(?P<fyear>\d{{4}})\b)?)"
    rf"|(?P<month>\b(?P<mmon>{_MON})\.?\s+(?P<myear>\d{{4}})\b)"
    rf"|(?P<money>(?:₱|\bPHP\s?|(?<![A-Za-z])P(?=\d))(?P<mnum>{_NUM}))"
    rf"|(?P<pesos>(?P<pnum>{_NUM})\s?pesos?\b)"
    rf"|(?P<percent>(?P<cnum>{_NUM})\s?%)"
    rf"|(?P<months>(?P<onum>{_NUM})[\s-]months?\b)"
    rf"|(?P<years>(?P<ynum>{_NUM})[\s-]years?\b)"
    rf"|(?P<words>\b(?P<wnum>{_WORDNUM})[\s-](?P<wunit>months?|years?|percent|per\s?cent)\b)"
    rf"|(?P<number>{_NUM})",
    re.IGNORECASE,
)
ORDINAL: Final = re.compile(r"(?:st|nd|rd|th)(?![A-Za-z])", re.IGNORECASE)
# A multiplier after a number: the figure is never written that way.
SCALE: Final = re.compile(r"\s?(?:k|m|b|mn|bn|thousand|million|billion)\b", re.IGNORECASE)
# Words with digits that are names of things, not numbers: 13th-month pay.
TERMS: Final = re.compile(r"\b13th[\s-]month\b", re.IGNORECASE)
WORD: Final = re.compile(r"[\w:@./\-]")  # what a ref is made of
SHOWN_UNMATCHED: Final = 12  # the most unmatched numbers named back to the model
MAX_PLACES: Final = 6  # more decimals than this is never a figure
MAX_DIGITS: Final = 18


@dataclass(frozen=True)
class Token:
    """One number read out of a text, with every value it may stand for."""

    start: int
    end: int
    text: str  # as written: a code is its whole word, a scaled number with its multiplier
    kind: Kind
    pools: tuple[str, ...] = ()  # where its value may be: money, months, percent, counts
    value: Decimal | None = None
    places: int = 0
    dates: tuple[date, ...] = ()  # a date: the days it may be
    year_month: tuple[int, int] | None = None  # a month (Feb 2028), or a bare year (month 0)
    day_of: tuple[int, int] | None = None  # a date with no year: (month, day)


def _decimal(text: str) -> tuple[Decimal, int]:
    """The value and how many decimals it was written with."""
    plain = text.replace(",", "")
    return Decimal(plain), len(plain.partition(".")[2])


def _month(name: str) -> int:
    return _MONTHS[name[:3].lower()]


def _day(year: int, month: int, day: int) -> tuple[date, ...]:
    try:
        return (date(year, month, day),)
    except ValueError:
        return ()  # not a real date (Feb 30, 2028): never a match


def _word_value(words: str) -> Decimal:
    parts = re.split(r"[\s-]+", words.lower())
    if parts[0] in _TENS:
        tens = (_TENS.index(parts[0]) + 2) * 10
        return Decimal(tens + (_UNITS.index(parts[1]) if len(parts) > 1 else 0))
    return Decimal(_UNITS.index(parts[0]))


def _strip_names(text: str, names: Iterable[str]) -> str:
    for name in sorted({n for n in names if any(c.isdigit() for c in n)}, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
        text = pattern.sub(lambda m: " " * len(m.group()), text)
    return TERMS.sub(lambda m: " " * len(m.group()), text)


def _whole_word(text: str, start: int, end: int) -> tuple[int, int]:
    while start > 0 and WORD.match(text[start - 1]):
        start -= 1
    while end < len(text) and WORD.match(text[end]):
        end += 1
    while end > start and text[end - 1] in ".:-/":
        end -= 1
    while start < end and text[start] in ".:-/":
        start += 1
    return start, end


def scan(text: str, names: Iterable[str] = ()) -> list[Token]:
    """Each number in the text, in order. Names (people's and things') and fixed terms are left
    out first; a word with two numbers in it (`debt1-W1`) is one code."""
    text = _strip_names(text, names)
    found: list[Token] = []
    word_end = -1
    for m in TOKEN.finditer(text):
        token = _token(text, m)
        if token.kind == "code" and token.start < word_end:
            continue
        if token.kind == "code":
            word_end = token.end
        found.append(token)
    return found


def _token(text: str, m: re.Match[str]) -> Token:
    start, end, written = m.start(), m.end(), m.group().strip()
    if m.group("iso"):
        days = _day(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
        return Token(start, end, written, "date", dates=days)
    if m.group("slash"):
        a, b, y = int(m.group("s1")), int(m.group("s2")), int(m.group("s3"))
        full = y + 2000 if y < 100 else y
        days = tuple(dict.fromkeys(_day(full, b, a) + _day(full, a, b)))  # D/M/Y or M/D/Y
        return Token(start, end, written, "date", dates=days)
    if m.group("date") or m.group("first"):
        mon = _month(m.group("dmon") or m.group("fmon"))
        day = int(m.group("day") or m.group("fday"))
        written_year = m.group("dyear") or m.group("fyear")
        if written_year is None:
            return Token(start, end, written, "date", day_of=(mon, day))
        return Token(start, end, written, "date", dates=_day(int(written_year), mon, day))
    if m.group("month"):
        ym = (int(m.group("myear")), _month(m.group("mmon")))
        return Token(start, end, written, "month", year_month=ym)
    if m.group("words"):
        value = _word_value(m.group("wnum"))
        unit = m.group("wunit").lower()
        if unit.startswith("month"):
            return Token(start, end, written, "months", ("months",), value)
        if unit.startswith("year"):
            return Token(start, end, written, "months", ("years",), value)
        return Token(start, end, written, "percent", ("percent",), value)
    kind: Kind
    pools: tuple[str, ...]
    if m.group("money") or m.group("pesos"):
        kind, raw, pools = "money", m.group("mnum") or m.group("pnum"), ("money",)
    elif m.group("percent"):
        kind, raw, pools = "percent", m.group("cnum"), ("percent",)
    elif m.group("months"):
        kind, raw, pools = "months", m.group("onum"), ("months",)
    elif m.group("years"):
        kind, raw, pools = "months", m.group("ynum"), ("years",)
    else:
        kind, raw, pools = "number", m.group("number"), ("money", "months", "percent", "counts")
    before = text[start - 1] if start > 0 else " "
    after = text[end:]
    scale = SCALE.match(text, end) if kind in ("money", "number") else None
    if kind == "number" and (
        before.isalpha()
        or before == "_"
        or (scale is None and after[:1].isalpha() and not ORDINAL.match(after))
    ):
        ws, we = _whole_word(text, start, end)  # run into letters: a code (`debt1-W1`)
        return Token(ws, we, text[ws:we], "code")
    if scale is not None:
        return Token(start, scale.end(), text[start : scale.end()].strip(), "scaled")
    value, places = _decimal(raw)
    if kind == "number" and places == 0 and "," not in raw and 1900 <= value <= 2100:
        bare = (int(value), 0)  # a bare year: any date in it, or the number itself
        return Token(start, end, written, kind, pools, value, places, year_month=bare)
    return Token(start, end, written, kind, pools, value, places)


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
